"""at home スクレイパー（既定で無効）.

【無効の理由】
アットホームの利用規約 第4条(13) は、
「クローラー、スパイダー及びこれらに類似するプログラムや処理技術等を用いて
  本サイトの情報を取得する行為」
を明示的に禁止している。
（あわら市空き家バンクの実体サイト awara-c18208.akiya-athome.jp も
  第4条(7) で「通常のWebブラウザによる使用以外での特殊なアクセス行為」を禁止）

したがって本モジュールはスクレイピングを行わない。回避策も実装しない。
at home 掲載の空き家物件は、あわら市公式ページ(awara スクレイパー)が実質的にカバーする。
市場物件は README の手動チェック用 URL を参照。

将来 at home が公式 API / RSS を提供した場合は、ここに実装を追加する。
"""
from __future__ import annotations

from awara_monitor.models import ScrapedListing

from .base import BaseScraper, ScraperDisabled

REASON = (
    "at home 利用規約 第4条(13) によりクローラーでの情報取得が禁止されているため、"
    "自動監視の対象外です（回避は行いません）。"
)


class AtHomeScraper(BaseScraper):
    name = "athome"
    label = "at home"
    enabled = False

    def fetch(self) -> list[ScrapedListing]:
        raise ScraperDisabled(REASON)
