"""国土地理院(GSI)の住所検索APIによるジオコーディング.

  https://msearch.gsi.go.jp/address-search/AddressSearch?q=<住所>

- 無料・APIキー不要・利用登録不要（国土地理院の地理院地図と同じ公開API）。
- 結果は SQLite にキャッシュして再問い合わせを避ける（ヒットしなかった住所も
  ネガティブキャッシュする）。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests

from . import config, normalize

log = logging.getLogger(__name__)


class Geocoder:
    def __init__(self, db, session: Optional[requests.Session] = None) -> None:
        self.db = db
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", config.USER_AGENT)
        self._last_call = 0.0

    # -- public ---------------------------------------------------------------
    def geocode(self, address: str) -> Optional[tuple[float, float]]:
        """住所 → (lat, lon)。判定できなければ None。"""
        address = (address or "").strip()
        if not address:
            return None

        from .database import _MISSING

        cached = self.db.get_geocode(address)
        if cached is not _MISSING:
            return cached  # (lat, lon) か None（ネガティブキャッシュ）

        result: Optional[tuple[float, float]] = None
        for query in self._candidates(address):
            result = self._call(query)
            if result:
                break

        self.db.put_geocode(address, result)
        return result

    # -- internal -----------------------------------------------------------
    @staticmethod
    def _candidates(address: str) -> list[str]:
        a = normalize.to_halfwidth(address).strip()
        cands = [a]
        # 丁目 / 番地を落として粗くする
        trimmed = re.sub(r"(丁目|字).*$", r"\1", a)
        if trimmed != a:
            cands.append(trimmed)
        town = normalize.extract_town(a)
        if town:
            cands.append(f"福井県あわら市{town}")
        cands.append("福井県あわら市")
        # 重複除去・順序保持
        seen: set[str] = set()
        out = []
        for c in cands:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _call(self, query: str) -> Optional[tuple[float, float]]:
        elapsed = time.monotonic() - self._last_call
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        try:
            resp = self.session.get(
                config.GSI_GEOCODE_URL,
                params={"q": query},
                timeout=config.HTTP_TIMEOUT,
            )
            self._last_call = time.monotonic()
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("ジオコーディング失敗 q=%r: %s", query, exc)
            self._last_call = time.monotonic()
            return None

        if not isinstance(data, list) or not data:
            return None

        # あわら市の範囲内に絞って最良候補を選ぶ
        best = None
        for feat in data:
            try:
                lon, lat = feat["geometry"]["coordinates"][:2]
            except (KeyError, TypeError, ValueError):
                continue
            if not (35.8 < lat < 36.5 and 135.9 < lon < 136.4):
                continue
            title = feat.get("properties", {}).get("title", "")
            score = 2 if "あわら" in title else 1
            if best is None or score > best[0]:
                best = (score, float(lat), float(lon))
        if best:
            return best[1], best[2]
        # 範囲チェックに落ちても先頭を最後の手段として返す
        try:
            lon, lat = data[0]["geometry"]["coordinates"][:2]
            return float(lat), float(lon)
        except (KeyError, TypeError, ValueError, IndexError):
            return None
