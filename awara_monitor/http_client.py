"""サイトへの負荷を抑えた HTTP クライアントと robots.txt チェック."""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from . import config

log = logging.getLogger(__name__)


class ScrapeError(Exception):
    """スクレイピング一般の失敗。"""


class AccessBlockedError(ScrapeError):
    """アクセス制限（403 / 429 / robots.txt 不許可 等）。

    ※ この例外が出た場合、回避策は実装しない。エラーとして扱う。
    """


class ScraperDisabled(ScrapeError):
    """規約・アクセス制限により、この監視元は無効化されている。"""


class PoliteSession:
    """待機・リトライ・UA を管理する requests セッションのラッパー。"""

    def __init__(
        self,
        user_agent: str = config.USER_AGENT,
        delay: float = config.REQUEST_DELAY_SECONDS,
        timeout: int = config.HTTP_TIMEOUT,
        retries: int = config.HTTP_MAX_RETRIES,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en;q=0.8",
            }
        )

    def _respect_delay(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET。403/429/5xx は AccessBlockedError / ScrapeError にする。"""
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._respect_delay()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:  # ネットワーク系
                last_exc = exc
                log.warning("GET failed (%s/%s) %s: %s", attempt + 1, self.retries + 1, url, exc)
                time.sleep(2 * (attempt + 1))
                continue
            finally:
                self._last_request_at = time.monotonic()

            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "15"))
                if attempt < self.retries:
                    log.warning("429 for %s, waiting %ss", url, wait)
                    time.sleep(min(wait, 60))
                    continue
                raise AccessBlockedError(f"HTTP 429 (レート制限) {url}")
            if resp.status_code in (401, 403):
                raise AccessBlockedError(
                    f"HTTP {resp.status_code} {url} — サイト側でアクセスが制限されています"
                )
            if 500 <= resp.status_code < 600:
                if attempt < self.retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise ScrapeError(f"HTTP {resp.status_code} (サーバエラー) {url}")
            raise ScrapeError(f"HTTP {resp.status_code} {url}")

        raise ScrapeError(f"リクエスト失敗: {url}: {last_exc}")


class RobotsGate:
    """robots.txt を取得・キャッシュし、User-agent: * のルールで可否を判定する。"""

    def __init__(self, session: PoliteSession, user_agent: str = config.USER_AGENT) -> None:
        self.session = session
        self.user_agent = user_agent
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._cache:
            return self._cache[origin]

        rp = urllib.robotparser.RobotFileParser()
        robots_url = origin + "/robots.txt"
        try:
            resp = self.session.get(robots_url)
            rp.parse(resp.text.splitlines())
        except AccessBlockedError:
            # robots.txt 自体がブロックされている → 保守的に「不許可」扱い
            log.warning("robots.txt がブロックされました: %s", robots_url)
            self._cache[origin] = None
            return None
        except ScrapeError as exc:
            # robots.txt が無い（404 等）→ 制限なしとみなす
            log.info("robots.txt を取得できませんでした（制限なしとみなす）: %s (%s)", robots_url, exc)
            rp.parse([])  # 空 = 全許可
        self._cache[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._parser_for(url)
        if rp is None:
            return False
        try:
            # robotparser は User-agent 行と引数を突き合わせる。
            # 該当する専用エントリが無ければ自動的に "User-agent: *" が適用される。
            return rp.can_fetch(self.user_agent, url)
        except Exception:  # pragma: no cover - robotparser の想定外
            return True

    def require(self, url: str) -> None:
        if not self.allowed(url):
            raise AccessBlockedError(f"robots.txt で許可されていません: {url}")
