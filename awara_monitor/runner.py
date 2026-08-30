"""監視の実行本体（main.py から呼ばれる）."""
from __future__ import annotations

import logging
import os
import sys

from . import config
from .database import Database
from .geocode import Geocoder
from .http_client import (
    AccessBlockedError,
    PoliteSession,
    RobotsGate,
    ScraperDisabled,
)
from .models import now_iso
from .notify import DiscordNotifier, SITE_LABELS
from .pipeline import RunResult, run as run_pipeline

log = logging.getLogger("awara_monitor")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(config.LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def run(verbose: bool = False) -> int:
    setup_logging(verbose)
    started = now_iso()
    log.info("=== あわら市・戸建て物件 監視 開始 %s ===", started)
    log.info("有効な監視元: %s", ", ".join(config.ENABLED_SOURCES))
    if config.DRY_RUN:
        log.info("DRY-RUN モード: Discord へは送信しません")
    if not config.DISCORD_WEBHOOK_URL and not config.DRY_RUN:
        log.warning("DISCORD_WEBHOOK_URL が未設定です。通知はスキップされます。")

    from scrapers import build_scrapers  # 遅延 import（循環回避）

    db = Database(config.DB_PATH)
    db.init_schema()

    session = PoliteSession()
    gate = RobotsGate(session)
    geocoder = Geocoder(db)

    scrapers = build_scrapers(list(config.ENABLED_SOURCES), session, gate)

    scraped: dict[str, list] = {}
    ok_sources: set[str] = set()
    errors: list[tuple[str, str]] = []

    for scraper in scrapers:
        try:
            items = scraper.fetch()
            scraped[scraper.name] = items
            ok_sources.add(scraper.name)
            log.info("[%s] %d 件取得", scraper.name, len(items))
        except ScraperDisabled as exc:
            log.info("[%s] 無効化されています: %s", scraper.name, exc)
        except AccessBlockedError as exc:
            errors.append((scraper.name, f"アクセス制限（回避しません）: {exc}"))
            log.error("[%s] アクセス制限: %s", scraper.name, exc)
        except Exception as exc:  # noqa: BLE001 - 1サイトの失敗で他を止めない
            errors.append((scraper.name, f"{type(exc).__name__}: {exc}"))
            log.exception("[%s] 取得失敗", scraper.name)

    result = run_pipeline(db, scraped, ok_sources, geocoder)

    notifier = DiscordNotifier()
    _notify(db, notifier, result, errors)

    summary = _build_summary(started, scraped, ok_sources, errors, result, db)
    db.write_run_log(started, summary["raw"])
    _write_step_summary(summary["markdown"])
    _write_run_summary_file(summary["markdown"])

    db.close()

    log.info("=== 監視 終了 ===\n%s", summary["markdown"])

    # 有効な監視元がすべて失敗した場合のみ異常終了
    enabled_real = [s for s in scrapers if s.enabled]
    if enabled_real and not ok_sources:
        return 1
    return 0


def _notify(db, notifier: DiscordNotifier, result: RunResult, errors) -> None:
    for ev in result.new_properties:
        try:
            notifier.send_new_property(ev)
            db.record_notification("new", ev.dedup_key())
        except Exception:
            log.exception("新着通知の送信に失敗: property#%s", ev.internal_id)

    for ev in result.price_changes:
        try:
            notifier.send_price_change(ev)
            db.record_notification(
                "price_change", f"{ev.internal_id}:{ev.old_price}->{ev.new_price}"
            )
        except Exception:
            log.exception("価格変更通知の送信に失敗: property#%s", ev.internal_id)

    for source, message in errors:
        if db.should_send_error(source, config.ERROR_NOTIFY_COOLDOWN_HOURS):
            try:
                notifier.send_error(source, message)
                db.record_notification("error", source)
            except Exception:
                log.exception("エラー通知の送信に失敗: %s", source)
        else:
            log.info("[%s] エラー通知はクールダウン中のため送信スキップ", source)

    if config.SEND_MANUAL_CHECK_REMINDER:
        try:
            notifier.send_manual_check_reminder()
        except Exception:
            log.exception("手動チェックリマインダーの送信に失敗")


def _build_summary(started, scraped, ok_sources, errors, result: RunResult, db) -> dict:
    stats = db.stats()
    lines = [
        "# あわら市・戸建て物件 監視結果",
        "",
        f"- 実行開始: {started}",
        f"- 取得成功サイト: {', '.join(sorted(ok_sources)) or 'なし'}",
        f"- 取得件数: "
        + ", ".join(f"{k}={len(v)}" for k, v in scraped.items())
        + (" (なし)" if not scraped else ""),
        "",
        "## 検出結果",
        f"- 🚨 新着物件: **{len(result.new_properties)}**",
        f"- 💰 価格変更: **{len(result.price_changes)}**",
        f"- 🗑 掲載終了: {len(result.delisted_internal_ids)}",
        f"- 処理件数: {result.processed} / 種別除外: {result.skipped_excluded} / エリア外: {result.skipped_out_of_area}",
        f"- 重複統合: {result.dedup_merges} / 重複候補: {result.dedup_candidates}",
        "",
        "## DB 統計",
        f"- 物件(active/total): {stats['properties_active']}/{stats['properties_total']}",
        f"- 掲載(active/total): {stats['listings_active']}/{stats['listings_total']}",
        f"- 価格変更履歴: {stats['price_changes']}",
    ]
    if result.new_properties:
        lines += ["", "### 新着物件"]
        for ev in result.new_properties:
            price = ev.listing.price
            lines.append(
                f"- [{'売買' if ev.listing.deal_type == 'sale' else '賃貸'}] "
                f"{price:,}円 / {ev.listing.layout} / {ev.listing.address} / "
                f"{ev.dist.display()} / {', '.join(SITE_LABELS.get(s, s) for s in ev.sites)}"
            )
    if errors:
        lines += ["", "## ⚠️ エラー"]
        for source, msg in errors:
            lines.append(f"- **{source}**: {msg}")

    markdown = "\n".join(lines)
    return {
        "markdown": markdown,
        "raw": {
            "started": started,
            "ok_sources": sorted(ok_sources),
            "counts": {k: len(v) for k, v in scraped.items()},
            "result": result.summary(),
            "errors": [{"source": s, "message": m} for s, m in errors],
            "stats": stats,
        },
    }


def _write_step_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    except OSError as exc:  # pragma: no cover
        log.warning("GITHUB_STEP_SUMMARY への書き込みに失敗: %s", exc)


def _write_run_summary_file(markdown: str) -> None:
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(config.SUMMARY_PATH, "w", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    except OSError as exc:  # pragma: no cover
        log.warning("サマリファイルの書き込みに失敗: %s", exc)
