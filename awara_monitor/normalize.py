"""物件テキストのパース / 正規化ユーティリティ.

各サイトのスクレイパーから使う共通処理。サイト固有の DOM 依存はここに置かない。
"""
from __future__ import annotations

import datetime
import math
import re
import unicodedata
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# 文字種の正規化
# --------------------------------------------------------------------------
_KANJI_DIGITS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}


def to_halfwidth(text: str) -> str:
    """全角英数字・記号を半角に。NFKC 正規化。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def kanji_chome_to_number(text: str) -> str:
    """「大溝三丁目」→「大溝3丁目」のように丁目直前の漢数字だけ算用数字化する。

    十を含む場合（十, 二十 など）にも対応。
    """
    if not text:
        return ""

    def repl(m: re.Match) -> str:
        kanji = m.group(1)
        return _kanji_num(kanji) + "丁目"

    return re.sub(r"([〇零一二三四五六七八九十]+)丁目", repl, text)


def _kanji_num(s: str) -> str:
    if "十" not in s:
        return "".join(_KANJI_DIGITS.get(c, c) for c in s)
    # 十, 一十, 二十三 ...
    total = 0
    cur = 0
    for c in s:
        if c == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = int(_KANJI_DIGITS.get(c, "0"))
    total += cur
    return str(total)


# --------------------------------------------------------------------------
# 価格
# --------------------------------------------------------------------------
def parse_price_yen(text: str, deal_type: str = "sale") -> Optional[int]:
    """価格テキストを「円」の整数にする。

    対応例:
      "1,399万円"          -> 13990000
      "770万円～800万円"   -> 7700000  (下限を採用)
      "100万円"            -> 1000000
      "2,980万円"          -> 29800000
      "6.7万円"            -> 67000
      "5万円"              -> 50000
      "4万5千円/月"        -> 45000
      "4万5000円"          -> 45000
      "55,000円"           -> 55000
      "5.5万円"            -> 55000
      "応相談" / ""        -> None
    """
    if not text:
        return None
    t = to_halfwidth(text)
    t = t.replace(",", "").replace("￥", "").replace("¥", "")
    t = t.replace("／", "/").strip()

    # 範囲表記は下限を採用
    t = re.split(r"[~〜～\-–]|から", t)[0].strip()

    # 「X万Y千円」
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(\d+)?\s*千", t)
    if m:
        man = float(m.group(1))
        sen = int(m.group(2)) if m.group(2) else 0
        return int(round(man * 10000 + sen * 1000))

    # 「X万Y円」/「X万Y000円」
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(\d+)\s*円", t)
    if m:
        man = float(m.group(1))
        rest = int(m.group(2))
        return int(round(man * 10000 + rest))

    # 「X万円」/「X万」
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", t)
    if m:
        return int(round(float(m.group(1)) * 10000))

    # 「NNNNN円」
    m = re.search(r"(\d{3,})\s*円", t)
    if m:
        return int(m.group(1))

    # 数字のみ（賃貸で "50000" のような値）
    m = re.fullmatch(r"\d{4,}", t)
    if m:
        return int(t)
    return None


# --------------------------------------------------------------------------
# 面積
# --------------------------------------------------------------------------
def parse_area_m2(text: str) -> Optional[float]:
    """"169.77m2（51.35坪）" / "84.11㎡" / "110平米" -> 169.77 / 84.11 / 110.0

    m^2 が見つからず坪だけある場合は坪 * 3.305785 で概算。
    """
    if not text:
        return None
    # <sup>2</sup> 由来の改行や空白（"169.77m\n2"）を除去してから判定する
    t = re.sub(r"\s+", "", to_halfwidth(text).replace(",", ""))
    # 範囲表記（"177.58m2～183.13m2"）は下限を採用
    t = re.split(r"[~〜]", t)[0]
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|㎡|平米|平方メートル)", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*坪", t)
    if m:
        return round(float(m.group(1)) * 3.305785, 2)
    return None


# --------------------------------------------------------------------------
# 築年
# --------------------------------------------------------------------------
_ERA_BASE = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def parse_built_year(text: str, *, today: Optional[datetime.date] = None) -> Optional[int]:
    """築年テキストを西暦（int）にする。

      "1990年12月"   -> 1990
      "1978年"       -> 1978
      "昭和53年"     -> 1978
      "平成10年3月"  -> 1998
      "令和2年"      -> 2020
      "築40年"       -> 現在年 - 40
      "新築" / "未入居" -> 現在年
    """
    if not text:
        return None
    t = to_halfwidth(text)
    today = today or datetime.date.today()

    if "新築" in t or "未入居" in t:
        return today.year

    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(\d+)\s*年", t)
    if m:
        return _ERA_BASE[m.group(1)] + int(m.group(2))

    m = re.search(r"(\d{4})\s*年", t)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= today.year + 2:
            return y

    m = re.search(r"築\s*(\d+)\s*年", t)
    if m:
        return today.year - int(m.group(1))
    return None


# --------------------------------------------------------------------------
# 間取り
# --------------------------------------------------------------------------
def parse_layout(text: str) -> str:
    if not text:
        return ""
    t = to_halfwidth(text).upper()
    m = re.search(r"\d+\s*[SLDKR]+(?:\+[SLDKR]+)?", t)
    if m:
        return m.group(0).replace(" ", "")
    t = collapse_spaces(t)
    return t[:20]


# --------------------------------------------------------------------------
# 住所 / 町名
# --------------------------------------------------------------------------
_CITY = "あわら市"


def normalize_address(address: str) -> str:
    """比較用に住所を正規化した文字列を返す。"""
    if not address:
        return ""
    a = to_halfwidth(address)
    a = re.sub(r"\s+", "", a)
    a = a.replace("福井県", "")
    a = kanji_chome_to_number(a)
    a = a.replace("大字", "").replace("字", "")
    # ハイフン類を統一
    a = re.sub(r"[‐‑‒–—―ー−]", "-", a)
    # "1丁目2番3号" -> "1-2-3"
    a = re.sub(r"(\d+)丁目", r"\1-", a)
    a = re.sub(r"(\d+)番地?(\d+)?号?", lambda m: m.group(1) + ("-" + m.group(2) if m.group(2) else ""), a)
    a = re.sub(r"-+", "-", a).strip("-")
    if not a.startswith(_CITY) and _CITY in a:
        a = _CITY + a.split(_CITY, 1)[1]
    return a


def extract_town(address: str) -> str:
    """住所から町名（丁目より前）を取り出す。

      "福井県あわら市大溝三丁目1-2" -> "大溝"
      "あわら市二面１"             -> "二面"
      "あわら市舟津"               -> "舟津"
    """
    if not address:
        return ""
    a = to_halfwidth(address).replace("福井県", "").strip()
    if _CITY in a:
        a = a.split(_CITY, 1)[1]
    a = kanji_chome_to_number(a)
    a = a.replace("大字", "").replace("字", "")
    # 最初の数字 / 丁目 / スペースまでを町名とみなす
    m = re.match(r"^([^\d\s]+?)(?:\d|丁目|$)", a)
    town = m.group(1) if m else a
    town = re.sub(r"[‐‑‒–—―ー−\-]+$", "", town).strip()
    return town


# --------------------------------------------------------------------------
# 駅・徒歩分数
# --------------------------------------------------------------------------
def parse_walk_minutes(
    station_texts: Iterable[str],
    aliases: Iterable[str],
    meters_per_minute: int = 80,
) -> tuple[Optional[int], str]:
    """駅情報テキスト（複数行）から、対象駅までの *徒歩* 分数を取り出す。

    - バス経由（"バスN分"）は採用しない。
    - "徒歩N分" / "歩N分" / "駅まで約Nm" / "Nm" に対応。
    返り値: (分, 元テキスト)。見つからなければ (None, "")。
    """
    aliases = tuple(aliases)
    for raw in station_texts:
        if not raw:
            continue
        line = to_halfwidth(raw)
        if not any(a in line for a in aliases):
            continue
        # 対象駅名を含む行のうち、駅名以降の部分を見る
        idx = max(line.find(a) for a in aliases if a in line)
        tail = line[idx:]
        # バス経由の記述しかない場合はスキップ（"歩" は bus 停からの徒歩なので不可）
        if "バス" in tail and "徒歩" not in tail and not re.search(r"駅\s*歩\s*\d", tail):
            continue
        m = re.search(r"(?:徒歩|歩)\s*(\d+)\s*分", tail)
        if m:
            return int(m.group(1)), raw.strip()
        m = re.search(r"(\d{2,4})\s*m", tail)
        if m:
            meters = int(m.group(1))
            return max(1, math.ceil(meters / meters_per_minute)), raw.strip()
    return None, ""


# --------------------------------------------------------------------------
# 種別フィルタ
# --------------------------------------------------------------------------
def looks_excluded(*texts: str, keywords: Iterable[str]) -> Optional[str]:
    """除外キーワードにヒットしたら、そのキーワードを返す（対象外）。"""
    blob = " ".join(to_halfwidth(t) for t in texts if t)
    for kw in keywords:
        if kw in blob:
            return kw
    return None


def has_banchi(address: str) -> bool:
    """番地（丁目の後の数字）まで含む住所かどうか。"""
    if not address:
        return False
    a = to_halfwidth(address)
    a = kanji_chome_to_number(a)
    return bool(re.search(r"\d+\s*[-‐−ー]\s*\d+|\d+番", a)) or bool(
        re.search(r"丁目\s*\d", a)
    )
