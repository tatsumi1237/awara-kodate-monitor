"""パイプライン → Discord 通知（dry-run）まで通しで動かす統合テスト。"""
from __future__ import annotations

from awara_monitor import pipeline
from awara_monitor.notify import DiscordNotifier

from .test_pipeline import run1_data, run2_data


def _drive(db, notifier, data, ok, geocoder):
    """runner.run() の通知部分と同じ流れ。"""
    result = pipeline.run(db, data, ok, geocoder)
    for ev in result.new_properties:
        notifier.send_new_property(ev)
        db.record_notification("new", ev.dedup_key())
    for ev in result.price_changes:
        notifier.send_price_change(ev)
        db.record_notification("price_change", f"{ev.internal_id}:{ev.old_price}->{ev.new_price}")
    return result


def test_full_flow_two_days(db, fake_geocoder):
    n = DiscordNotifier(webhook_url="", dry_run=True)

    r1 = _drive(db, n, run1_data(), {"awara", "suumo"}, fake_geocoder)
    assert len(r1.new_properties) == 2
    # 生成された payload がすべて Discord embed の形になっている
    for payload in n.sent:
        assert payload["embeds"][0]["title"] in ("🚨 新着物件", "💰 価格変更")
        assert isinstance(payload["embeds"][0]["description"], str)
        assert payload["embeds"][0]["description"]

    n.sent.clear()
    r2 = _drive(db, n, run2_data(run1_data()), {"awara", "suumo"}, fake_geocoder)
    titles = [p["embeds"][0]["title"] for p in n.sent]
    assert "💰 価格変更" in titles
    assert "🚨 新着物件" in titles
    assert len(r2.new_properties) == 1
    assert len(r2.price_changes) == 1

    # 3日目（変化なし）→ 通知ゼロ
    n.sent.clear()
    r3 = _drive(db, n, run2_data(run1_data()), {"awara", "suumo"}, fake_geocoder)
    assert n.sent == []
    assert not r3.new_properties and not r3.price_changes


def test_error_cooldown(db):
    from awara_monitor import config

    assert db.should_send_error("suumo", config.ERROR_NOTIFY_COOLDOWN_HOURS) is True
    db.record_notification("error", "suumo")
    assert db.should_send_error("suumo", config.ERROR_NOTIFY_COOLDOWN_HOURS) is False
    # 別サイトは独立
    assert db.should_send_error("awara", config.ERROR_NOTIFY_COOLDOWN_HOURS) is True
