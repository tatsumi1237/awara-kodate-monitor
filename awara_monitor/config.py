"""集中設定モジュール.

監視条件・距離しきい値・アクセス設定などをここで一元管理する。
環境変数で上書きできる項目は ``os.environ.get`` を使っている。
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default

# --------------------------------------------------------------------------
# 対象の駅
# --------------------------------------------------------------------------
STATION_NAME = "あわら湯のまち駅"

# 物件ページの駅名テキストと突き合わせるための表記ゆれ一覧
STATION_ALIASES = (
    "あわら湯のまち",
    "芦原湯のまち",
    "芦原湯の町",
)

# 国土地理院(GSI)住所検索APIで取得した「あわら湯のまち駅」の座標
#   https://msearch.gsi.go.jp/address-search/AddressSearch?q=あわら湯のまち駅
STATION_LON = 136.193792
STATION_LAT = 36.222948

# --------------------------------------------------------------------------
# 距離判定
# --------------------------------------------------------------------------
# 不動産の表示規約では「徒歩1分 = 80m」。
WALK_METERS_PER_MINUTE = 80
MAX_WALK_MINUTES = 15
# 徒歩15分 ≒ 1,200m を「対象」の基準にする
TARGET_DISTANCE_M = MAX_WALK_MINUTES * WALK_METERS_PER_MINUTE  # = 1200
# 1,200〜1,600m または町名だけの住所は「要確認」で通知する
UNCERTAIN_DISTANCE_M = 1600
# 直線距離 → 徒歩距離 へのおおまかな補正係数
DETOUR_FACTOR = 1.3

# 番地が取れなくても、町名だけで「駅至近」と判断してよいエリア。
# （あわら湯のまち駅周辺の温泉街・中心部）
NEAR_STATION_TOWNS = (
    "温泉",
    "二面",
    "舟津",
    "春宮",
    "花乃杜",
    "国影",
    "田中々",
    "北疋田",
)

# --------------------------------------------------------------------------
# 物件条件
# --------------------------------------------------------------------------
SALE_MAX_PRICE = _env_int("MONITOR_SALE_MAX_PRICE", 2_500_000)  # 円
RENT_MAX_PRICE = _env_int("MONITOR_RENT_MAX_PRICE", 50_000)    # 円 / 月

# 物件種別: 「一戸建て」以外を除外するためのキーワード。
# 物件名・種別テキスト・間取り・その他備考のいずれかに含まれていたら対象外。
EXCLUDE_KEYWORDS = (
    "マンション",
    "アパート",
    "土地",
    "更地",
    "宅地",
    "店舗",
    "事務所",
    "倉庫",
    "工場",
    "ビル",
    "区分所有",
    "収益",
    "テナント",
    "駐車場",
    "資材置場",
)

# Discord 上で強調表示する売買価格帯（円）
PRICE_BANDS = (1_000_000, 1_500_000, 2_000_000, 2_500_000)

# --------------------------------------------------------------------------
# HTTP アクセス（サイトへの負荷を最小化する）
# --------------------------------------------------------------------------
USER_AGENT = os.environ.get(
    "MONITOR_USER_AGENT",
    "AwaraKodateMonitor/1.0 (personal, non-commercial property watch; "
    "1 request/day; +https://github.com/)",
)
# 1リクエストごとの待機秒数
REQUEST_DELAY_SECONDS = _env_float("MONITOR_REQUEST_DELAY", 4.0)
HTTP_TIMEOUT = _env_int("MONITOR_HTTP_TIMEOUT", 30)
HTTP_MAX_RETRIES = 2
# 1サイト1回の実行で取得してよい「詳細ページ / PDF」の上限
MAX_DETAIL_FETCHES_PER_SITE = _env_int("MONITOR_MAX_DETAIL_FETCHES", 8)
# 一覧のページ送りの上限（あわら市は実質1ページ）
MAX_LIST_PAGES = _env_int("MONITOR_MAX_LIST_PAGES", 5)

# --------------------------------------------------------------------------
# パス
# --------------------------------------------------------------------------
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_PKG_DIR)
DATA_DIR = os.environ.get("MONITOR_DATA_DIR", os.path.join(ROOT, "data"))
DB_PATH = os.environ.get("MONITOR_DB_PATH", os.path.join(DATA_DIR, "properties.db"))
SUMMARY_PATH = os.path.join(DATA_DIR, "last_run_summary.md")
LOG_PATH = os.path.join(ROOT, "monitor.log")

# --------------------------------------------------------------------------
# Discord 通知
# --------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
# 管理者向けエラー通知を別チャンネルに送りたい場合のみ設定（未設定なら上と同じ）
DISCORD_ERROR_WEBHOOK_URL = (
    os.environ.get("DISCORD_ERROR_WEBHOOK_URL", "").strip() or DISCORD_WEBHOOK_URL
)
# 同一サイトのエラーを連続通知しないためのクールダウン（時間）
ERROR_NOTIFY_COOLDOWN_HOURS = _env_int("MONITOR_ERROR_COOLDOWN_HOURS", 20)

# 通知を送らずログ出力だけ行う
DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "").lower() in ("1", "true", "yes")

# --------------------------------------------------------------------------
# 有効なスクレイパー
#   awara : あわら市 空き家バンク（市公式ページ / robots.txt なし・公的情報）
#   suumo : SUUMO（robots.txt 許可パスのみ・利用規約にクローラー禁止条項なし）
#
#   athome / homes は既定で無効:
#     - at home  : 利用規約 第4条(13) でクローラーによる取得を明示的に禁止
#     - LIFULL HOME'S : 非ブラウザ UA を HTTP 403 でブロック（回避は行わない）
# --------------------------------------------------------------------------
_enabled_raw = os.environ.get("MONITOR_ENABLED_SOURCES", "").strip() or "awara,suumo"
ENABLED_SOURCES = tuple(s.strip() for s in _enabled_raw.split(",") if s.strip())

# 手動確認用（README にも記載）。スクレイピングはしない。
MANUAL_CHECK_URLS = {
    "at home（売買・戸建て）": "https://www.athome.co.jp/kodate/chuko/fukui/awara-city/list/",
    "at home（賃貸）": "https://www.athome.co.jp/chintai/fukui/awara-city/list/",
    "LIFULL HOME'S（売買・戸建て）": "https://www.homes.co.jp/kodate/chuko/fukui/awara-city/list/",
    "LIFULL HOME'S（賃貸）": "https://www.homes.co.jp/chintai/fukui/awara-city/list/",
    "SUUMO（RSSリーダー用・中古戸建て）": (
        "https://suumo.jp/chukoikkodate/fukui/sc_awara/  ページ右上「RSS登録」"
    ),
}
# 手動確認リンクを毎日 Discord に投げるか
SEND_MANUAL_CHECK_REMINDER = os.environ.get(
    "MONITOR_SEND_MANUAL_REMINDER", ""
).lower() in ("1", "true", "yes")

GSI_GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
