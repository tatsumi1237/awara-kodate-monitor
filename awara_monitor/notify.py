"""Discord Webhook 通知.

Webhook URL はコードに書かず、環境変数 / GitHub Secrets(DISCORD_WEBHOOK_URL) から渡す。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from . import config
from .models import DistanceResult, ScrapedListing, today_str
from .pipeline import NewPropertyEvent, PriceChangeEvent

log = logging.getLogger(__name__)

SITE_LABELS = {
    "awara": "あわら市空き家バンク",
    "suumo": "SUUMO",
    "athome": "at home",
    "homes": "LIFULL HOME'S",
}

# Discord 埋め込みの色（10進）
COLOR_RED = 0xE74C3C
COLOR_ORANGE = 0xE67E22
COLOR_YELLOW = 0xF1C40F
COLOR_GREEN = 0x2ECC71
COLOR_BLUE = 0x3498DB
COLOR_GREY = 0x95A5A6


def man(price: Optional[int]) -> str:
    """円 → 「◯◯万円」等の読みやすい表記。"""
    if price is None:
        return "価格応相談"
    if price >= 10000 and price % 10000 == 0:
        return f"{price // 10000}万円"
    if price >= 10000:
        return f"{price / 10000:.1f}万円"
    return f"{price:,}円"


def rent_label(price: Optional[int]) -> str:
    if price is None:
        return "賃料応相談"
    return f"月額 {price:,}円"


def _price_band(deal_type: str, price: Optional[int]) -> tuple[str, int]:
    """売買価格帯の強調ラベルと色。"""
    if deal_type != "sale" or price is None:
        return "", COLOR_BLUE
    if price <= 1_000_000:
        return "🔥🔥🔥 100万円以下", COLOR_RED
    if price <= 1_500_000:
        return "🔥🔥 150万円以下", COLOR_ORANGE
    if price <= 2_000_000:
        return "🔥 200万円以下", COLOR_YELLOW
    if price <= 2_500_000:
        return "250万円以下", COLOR_GREEN
    return "", COLOR_BLUE


def _area_line(label: str, value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{label}：{value:g}㎡"


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str = config.DISCORD_WEBHOOK_URL,
        error_webhook_url: str = config.DISCORD_ERROR_WEBHOOK_URL,
        dry_run: bool = config.DRY_RUN,
    ) -> None:
        self.webhook_url = webhook_url
        self.error_webhook_url = error_webhook_url or webhook_url
        self.dry_run = dry_run
        self.sent: list[dict] = []  # テスト用

    # -- low level ---------------------------------------------------------
    def _post(self, url: str, payload: dict) -> None:
        self.sent.append(payload)
        if self.dry_run or not url:
            log.info("[DRY-RUN] Discord payload: %s", _short(payload))
            return
        for attempt in range(4):
            try:
                resp = requests.post(url, json=payload, timeout=20)
            except requests.RequestException as exc:
                log.warning("Discord POST 失敗 (%s): %s", attempt + 1, exc)
                time.sleep(3)
                continue
            if resp.status_code in (200, 204):
                time.sleep(0.6)  # レート制限に配慮
                return
            if resp.status_code == 429:
                retry = float(resp.headers.get("Retry-After", "2"))
                try:
                    retry = float(resp.json().get("retry_after", retry))
                except Exception:
                    pass
                log.warning("Discord 429、%.1fs 待機", retry)
                time.sleep(min(retry + 0.5, 10))
                continue
            log.error("Discord POST HTTP %s: %s", resp.status_code, resp.text[:300])
            return
        log.error("Discord 通知を諦めました")

    # -- public ---------------------------------------------------------
    def send_new_property(self, ev: NewPropertyEvent) -> None:
        self._post(self.webhook_url, self._new_payload(ev))

    def send_price_change(self, ev: PriceChangeEvent) -> None:
        self._post(self.webhook_url, self._price_payload(ev))

    def send_error(self, source: str, message: str) -> None:
        label = SITE_LABELS.get(source, source)
        payload = {
            "embeds": [
                {
                    "title": "⚠️ 監視エラー",
                    "description": f"**{label}** の取得に失敗しました。\n```\n{message[:1500]}\n```\n"
                    "GitHub Actions のログを確認してください。",
                    "color": COLOR_GREY,
                }
            ]
        }
        self._post(self.error_webhook_url, payload)

    def send_manual_check_reminder(self) -> None:
        lines = [f"・{name}\n{url}" for name, url in config.MANUAL_CHECK_URLS.items()]
        payload = {
            "embeds": [
                {
                    "title": "🔎 手動チェック（自動取得できないサイト）",
                    "description": "\n\n".join(lines),
                    "color": COLOR_GREY,
                    "footer": {"text": "at home は規約により、HOME'S はアクセス制限により自動監視対象外"},
                }
            ]
        }
        self._post(self.webhook_url, payload)

    def send_run_summary(self, text: str) -> None:
        self._post(self.error_webhook_url, {"content": text[:1900]})

    # -- payload builders ---------------------------------------------------------
    def _common_fields(self, listing: ScrapedListing, dist: DistanceResult,
                       sites: list[str], urls: list[str]) -> list[str]:
        lines: list[str] = []
        if listing.layout:
            lines.append(f"🏠 {listing.layout}")
        if listing.address or listing.town:
            lines.append(f"📍 福井県あわら市{_addr_tail(listing)}")
        land = _area_line("土地", listing.land_area)
        bld = _area_line("建物", listing.building_area)
        if land:
            lines.append(f"📐 {land}")
        if bld:
            lines.append(f"🏠 {bld}")
        if listing.built_year:
            lines.append(f"🏗 築：{listing.built_year}年")
        lines.append(f"🚶 {dist.display()}")
        site_names = "\n".join(f"・{SITE_LABELS.get(s, s)}" for s in sites) or "・-"
        lines.append("掲載サイト：\n" + site_names)
        if urls:
            lines.append("物件URL：\n" + "\n".join(urls))
        return lines

    def _new_payload(self, ev: NewPropertyEvent) -> dict:
        listing, dist = ev.listing, ev.dist
        band, color = _price_band(listing.deal_type, listing.price)
        deal = "【売買】" if listing.deal_type == "sale" else "【賃貸】"
        price_str = man(listing.price) if listing.deal_type == "sale" else rent_label(listing.price)

        head = [deal]
        if band:
            head.append(f"**{band}**")
        head.append(f"価格：{price_str}")

        body = head + self._common_fields(listing, dist, ev.sites, ev.urls)
        body.append(f"検出日時：{today_str()}")
        if getattr(ev, "is_relist", False):
            body.append("（一度掲載終了した物件が再掲載されました）")
        elif ev.merged_from_other_site:
            body.append("（他サイトで既知の物件が再掲載されました）")

        return {
            "embeds": [
                {
                    "title": "🚨 新着物件",
                    "description": "\n".join(body),
                    "color": color,
                }
            ]
        }

    def _price_payload(self, ev: PriceChangeEvent) -> dict:
        listing, dist = ev.listing, ev.dist
        deal = "【売買】" if listing.deal_type == "sale" else "【賃貸】"
        down = ev.direction == "down"
        diff = abs(ev.new_price - ev.old_price)

        old_s = man(ev.old_price) if listing.deal_type == "sale" else f"{ev.old_price:,}円"
        new_s = man(ev.new_price) if listing.deal_type == "sale" else f"{ev.new_price:,}円"

        arrow = "　↓" if down else "　↑"
        tag = f"📉 値下げ（-{man(diff) if listing.deal_type == 'sale' else f'{diff:,}円'}）" if down \
            else f"📈 値上げ（+{man(diff) if listing.deal_type == 'sale' else f'{diff:,}円'}）"

        limit = config.SALE_MAX_PRICE if listing.deal_type == "sale" else config.RENT_MAX_PRICE
        crossed = ev.old_price > limit >= ev.new_price

        body = [deal, f"旧価格：{old_s}", arrow, f"新価格：{new_s}   {tag}"]
        if crossed:
            body.append("🎯 **条件価格以下になりました**")
        body += self._common_fields(listing, dist, ev.sites, ev.urls)
        body.append(f"検出日時：{today_str()}")

        color = COLOR_RED if down else COLOR_GREY
        return {
            "embeds": [
                {
                    "title": "💰 価格変更",
                    "description": "\n".join(body),
                    "color": color,
                }
            ]
        }


def _addr_tail(listing: ScrapedListing) -> str:
    addr = listing.address or ""
    for pref in ("福井県あわら市", "あわら市", "福井県"):
        if addr.startswith(pref):
            addr = addr[len(pref):]
    return addr or listing.town


def _short(payload: dict) -> str:
    try:
        return payload["embeds"][0]["description"][:200].replace("\n", " / ")
    except (KeyError, IndexError, TypeError):
        return str(payload)[:200]
