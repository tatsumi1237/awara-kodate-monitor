#!/usr/bin/env python3
"""あわら市・戸建て物件 自動監視システム エントリポイント.

使い方:
    python main.py            # 通常実行
    python main.py --dry-run  # Discord へ送信せず動作確認
    python main.py --verbose  # デバッグログ

環境変数:
    DISCORD_WEBHOOK_URL   Discord Webhook URL（GitHub では Secrets で設定）
    MONITOR_DRY_RUN       "true" で通知を送らない
    （その他は awara_monitor/config.py 参照）
"""
from __future__ import annotations

import argparse
import os
import sys

# `.env` があれば読み込む（ローカル実行用。GitHub Actions では Secrets を使う）
def _load_dotenv() -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="あわら市・戸建て物件 監視")
    parser.add_argument("--dry-run", action="store_true", help="Discord へ送信しない")
    parser.add_argument("--verbose", action="store_true", help="デバッグログ")
    args = parser.parse_args()

    _load_dotenv()
    if args.dry_run:
        os.environ["MONITOR_DRY_RUN"] = "true"

    # config は環境変数を読むので、ここで import する
    from awara_monitor.runner import run

    return run(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
