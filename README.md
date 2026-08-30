# あわら市・戸建て物件 自動監視システム

福井県あわら市で、**「あわら湯のまち駅」から徒歩15分程度以内**にある
条件に合う **一戸建て**（売買 250万円以下 / 賃貸 月5万円以下）を毎日自動でチェックし、
**新着物件**・**価格変更**を **Discord** に通知します。

- PC を起動しっぱなしにする必要はありません（GitHub Actions のクラウド上で1日1回実行）。
- 物件を勝手に購入・問い合わせ・予約する機能はありません。「探す作業の自動化」だけを行います。

---

## 目次

1. [仕組みの概要](#仕組みの概要)
2. [監視対象サイトと調査結果](#監視対象サイトと調査結果)
3. [GitHub へアップロードする方法](#github-へアップロードする方法)
4. [Discord Webhook の設定方法](#discord-webhook-の設定方法)
5. [GitHub Secrets の設定方法](#github-secrets-の設定方法)
6. [GitHub Actions を手動実行する方法](#github-actions-を手動実行する方法)
7. [監視頻度を変更する方法](#監視頻度を変更する方法)
8. [監視条件を変更する方法](#監視条件を変更する方法)
9. [エラーが発生した場合の確認方法](#エラーが発生した場合の確認方法)
10. [ローカルで動かす / テストする](#ローカルで動かす--テストする)
11. [データベースの内容](#データベースの内容)
12. [追加費用について](#追加費用について)

---

## 仕組みの概要

```
GitHub Actions（1日1回 / 手動実行も可）
  └─ python main.py
       1. あわら市 空き家バンク と SUUMO から物件一覧を取得
       2. 取得した物件を SQLite データベース(data/properties.db)に反映
       3. 前回DBと比較して「新着物件」を判定
       4. 前回価格と比較して「価格変更（値下げ / 値上げ）」を判定
       5. 同じ物件が複数サイトにあれば1件に統合
       6. 条件（種別・価格・駅からの距離）で絞り込み
       7. Discord へ通知
       8. 更新した data/properties.db をリポジトリにコミット（次回の比較用）
```

- **新着の判定**：サイトの「新着」表示は信用せず、**自前のDBに無かった物件**を新着とします。
- **距離の判定**：
  - 物件ページに「あわら湯のまち駅 徒歩◯分」があれば、それを使います。
  - なければ住所を[国土地理院のジオコーディングAPI](https://msearch.gsi.go.jp/)（無料）で座標に変換し、
    駅までの直線距離 × 1.3 で徒歩距離を概算します（徒歩15分 ≒ 1,200m）。
  - 確信が持てない場合は除外せず「**距離判定：要確認**」として通知します。
- **秘密情報**：Discord Webhook URL は **GitHub Secrets** だけで管理し、DB やコードには保存しません。

---

## 監視対象サイトと調査結果

| サイト | robots.txt / 規約 | 自動監視 | 備考 |
|---|---|---|---|
| **あわら市 空き家バンク**（市公式） | robots.txt なし・公的情報 | ✅ **対象** | 一覧はHTMLテーブル。面積・築年・駅距離は物件PDFから補完 |
| **SUUMO** | robots.txt で `/chukoikkodate/` `/ikkodate/` `/chintai/` は許可。利用規約にクローラー禁止条項なし | ✅ **対象** | 中古・新築の戸建て、賃貸戸建て。1日1回・待機付きで最小限アクセス |
| **at home** | 利用規約 第4条(13) が「クローラー等での情報取得」を**明示的に禁止** | ❌ 対象外 | 規約遵守のため取得しない。空き家物件は市公式ページでカバー |
| **LIFULL HOME'S** | 非ブラウザからのアクセスを **HTTP 403 でブロック** | ❌ 対象外 | ブラウザ偽装による回避はしない。空き家物件は市公式ページでカバー |

> at home / HOME'S の市場物件は、README 下部の「手動チェック用リンク」で確認してください。
> `MONITOR_SEND_MANUAL_REMINDER=true` にすると、その手動チェックURLを毎日 Discord に送れます。

### 追加費用が発生する可能性

- **ありません**（すべて無料の範囲で動きます）。
  - GitHub Actions：Public リポジトリは無料。Private でも無料枠 2,000分/月に対し、本システムは月あたり約 3〜5分。
  - 国土地理院ジオコーディング：無料・APIキー不要。
  - Discord Webhook：無料。
- 有料になり得るのは「Private リポジトリで極端に実行時間が伸びた場合」だけです（通常は起こりません）。

---

## GitHub へアップロードする方法

### 方法A：ブラウザだけで完結（初心者向け）

1. [GitHub](https://github.com/) にログイン（アカウントが無ければ無料登録）。
2. 右上の「+」→ **New repository**。
   - Repository name: `awara-kodate-monitor`（任意）
   - **Public**（推奨。Actions が無料無制限）または Private
   - 「Add a README file」などは**チェックしない**
   - **Create repository**
3. 次の画面で **uploading an existing file** をクリック。
4. この `awara-kodate-monitor` フォルダの中身を**すべて**ドラッグ&ドロップ。
   - `.github` フォルダも忘れずに（隠しフォルダ扱いのことがあります）。
   - `data/.gitkeep` も含めてください。
5. 下の **Commit changes** を押す。

### 方法B：Git コマンド

```bash
cd awara-kodate-monitor
git init
git add .
git commit -m "初回コミット: あわら市戸建て監視システム"
git branch -M main
git remote add origin https://github.com/＜あなたのユーザー名＞/awara-kodate-monitor.git
git push -u origin main
```

アップロードすると、`.github/workflows/test.yml` によって**自動でテストが実行**されます
（リポジトリの「Actions」タブで結果を確認できます）。

---

## Discord Webhook の設定方法

1. 通知を受け取りたい Discord サーバーで、対象チャンネルの ⚙️（**チャンネルの編集**）を開く。
2. **連携サービス**（Integrations）→ **ウェブフック**（Webhooks）→ **新しいウェブフック**。
3. 名前を付けて（例：`あわら物件bot`）、**ウェブフックURLをコピー**。
4. このURLは秘密です。次の手順で GitHub Secrets に登録します（コードには書きません）。

URL は `https://discord.com/api/webhooks/xxxxxxxxxxxx/yyyyyyyyyyyy` のような形式です。

---

## GitHub Secrets の設定方法

1. GitHub のリポジトリページ → **Settings**（設定）。
2. 左メニュー **Secrets and variables** → **Actions**。
3. **New repository secret** を押す。
   - **Name**： `DISCORD_WEBHOOK_URL` ← この名前で固定
   - **Secret**： さきほどコピーした Discord Webhook URL を貼り付け
   - **Add secret**
4. （任意）エラー通知を別チャンネルに送りたい場合は、同様に
   `DISCORD_ERROR_WEBHOOK_URL` を追加。

（任意の設定変更は「Variables」タブで `MONITOR_ENABLED_SOURCES` などの変数を追加します。
[監視条件を変更する方法](#監視条件を変更する方法) を参照。）

---

## GitHub Actions を手動実行する方法

1. リポジトリページ → **Actions** タブ。
2. 左の一覧から **「あわら市 戸建て物件 監視」** を選択。
3. 右側の **Run workflow** ボタンを押す。
   - `dry_run` に **true** を入れると、Discord へ送らずに動作だけ確認できます（初回のお試しに便利）。
   - `verbose` に true を入れると詳細ログが出ます。
4. **Run workflow**（緑のボタン）を押すと実行開始。数分で完了します。
5. 実行行をクリック → **monitor** ジョブ → 各ステップのログと、
   一番上の **Summary**（実行結果のまとめ）を確認できます。

---

## 監視頻度を変更する方法

`.github/workflows/monitor.yml` の `cron` を編集します。
**GitHub Actions の cron は UTC（世界標準時）指定**なので、日本時間から9時間引いた値にします。

```yaml
on:
  schedule:
    - cron: "0 20 * * *"   # UTC 20:00 = 日本時間 翌 05:00（初期値）
```

| やりたいこと | cron の書き方 |
|---|---|
| 毎日 日本時間 5:00（初期値） | `0 20 * * *` |
| 毎日 日本時間 7:00 | `0 22 * * *` |
| 毎日 日本時間 8:00 と 20:00 の2回 | `0 23 * * *` と `0 11 * * *` を2行 |
| 平日だけ 日本時間 6:00 | `0 21 * * 1-5` |

> 注意：GitHub の無料 cron は混雑時に数分〜十数分遅れて実行されることがあります（仕様）。
> アクセス集中を避けるため、初期値は早朝に設定しています。**頻度は上げすぎないでください**
> （サイトへの負荷とマナーの観点から、1日1〜2回を推奨）。

編集後は変更をコミット/プッシュすれば反映されます。

---

## 監視条件を変更する方法

### 方法1：GitHub の「Variables」で変更（コード編集不要・推奨）

**Settings → Secrets and variables → Actions → Variables タブ → New repository variable**

| 変数名 | 意味 | 例 |
|---|---|---|
| `MONITOR_SALE_MAX_PRICE` | 売買の上限価格（円） | `3000000`（300万円まで） |
| `MONITOR_RENT_MAX_PRICE` | 賃貸の上限（円/月） | `60000`（6万円まで） |
| `MONITOR_ENABLED_SOURCES` | 監視するサイト（カンマ区切り） | `awara,suumo` |
| `MONITOR_SEND_MANUAL_REMINDER` | at home/HOME'S の手動確認リンクを毎日通知 | `true` |
| `MONITOR_REQUEST_DELAY` | リクエスト間の待機秒数 | `5` |

> `monitor.yml` の「監視を実行」ステップに、これらの変数を渡す記述がすでに入っています。
> `MONITOR_SALE_MAX_PRICE` など未記載の変数を使いたい場合は、`monitor.yml` の `env:` に1行追加してください。

### 方法2：`awara_monitor/config.py` を直接編集

- 対象の駅・座標：`STATION_NAME` / `STATION_LAT` / `STATION_LON`
- 徒歩何分以内か：`MAX_WALK_MINUTES`（初期値 15）と `TARGET_DISTANCE_M`
- 「要確認」とする距離の上限：`UNCERTAIN_DISTANCE_M`（初期値 1600m）
- 駅至近とみなす町名：`NEAR_STATION_TOWNS`
- 除外する物件種別キーワード：`EXCLUDE_KEYWORDS`
- 価格帯の強調表示：`PRICE_BANDS`

### サイトのHTML構造が変わったとき

各サイトの取得処理は独立モジュールです。**壊れたサイトのファイルだけ**直せば済みます。

```
scrapers/
  awara.py   … あわら市 空き家バンク
  suumo.py   … SUUMO
  athome.py  … （規約により無効。実装なし）
  homes.py   … （アクセス制限により無効。実装なし）
```

`tests/fixtures/` に取得済みHTMLのサンプルがあります。構造を直したら
`python -m pytest tests/test_scraper_suumo.py` などで確認してください。

---

## エラーが発生した場合の確認方法

### 1サイトがエラーでも、他のサイトの監視は続行されます

例：SUUMO がエラー → あわら市空き家バンクの結果は通常どおり処理・通知されます。

### 確認手順

1. **GitHub Actions のログ**
   - Actions タブ → 該当の実行 → **monitor** ジョブ → 「監視を実行」ステップを開く。
   - エラー内容（`ERROR` 行）と、末尾のサマリを確認。
2. **実行結果サマリ**
   - 実行ページ上部の **Summary** に、取得件数・新着・価格変更・エラーがまとまっています。
3. **アーティファクト**
   - 実行ページ下部の **Artifacts** から `monitor-run-＜番号＞` をダウンロードすると、
     `monitor.log`（全ログ）と `data/last_run_summary.md` が入っています。
4. **Discord のエラー通知**
   - `⚠️ 監視エラー` という通知が届きます。
   - **同じサイトのエラーは約20時間に1回**しか通知しません（大量通知の防止）。

### よくあるエラー

| 症状 | 原因と対処 |
|---|---|
| `HTTP 403` / `アクセス制限` | サイト側で一時的にブロックされた可能性。基本は**放置**（回避策は実装しません）。継続するなら `MONITOR_REQUEST_DELAY` を増やす／実行時刻をずらす |
| `robots.txt で許可されていません` | サイトの robots.txt が変更された可能性。該当サイトのモジュールとURLを見直す |
| `物件一覧テーブルが見つかりません` | あわら市サイトのHTML構造変更。`scrapers/awara.py` を修正 |
| Discord に届かない | `DISCORD_WEBHOOK_URL` の Secret 名・値を確認。`dry_run` で実行してログに `[DRY-RUN]` payload が出るか確認 |
| DB がコミットされない | リポジトリの Settings → Actions → General → Workflow permissions を **Read and write** に |

---

## ローカルで動かす / テストする

Python 3.10 以上が必要です。

```bash
cd awara-kodate-monitor
python -m venv .venv
# Windows: .venv\Scripts\activate    /  macOS・Linux: source .venv/bin/activate
pip install -r requirements.txt

# .env を用意（.env.example をコピーして Webhook URL を記入）
cp .env.example .env

# 動作確認（Discord へは送らない）
python main.py --dry-run --verbose

# テスト
python -m pytest -q
```

`--dry-run` では実際にサイトへアクセスしますが、Discord へは送信せず
送信予定の内容をログに出します。

---

## データベースの内容

`data/properties.db`（SQLite）。**公開情報のみ**を保存します（秘密情報は入れません）。

| テーブル | 内容 |
|---|---|
| `properties` | 統合後の物件1件。internal_id / 売買・賃貸 / 価格 / 種別 / 住所 / 間取り / 土地・建物面積 / 築年 / 駅名 / 駅までの距離 / 距離判定方法 / 掲載サイト / URL / 初回検出日時 / 最終確認日時 / 前回価格 / 現在価格 / 状態(active・delisted) / 重複判定情報 |
| `listings` | サイトごとの掲載1件。properties に紐づく |
| `price_history` | 価格変更の履歴（旧価格・新価格・値下げ/値上げ・日時） |
| `dedup_candidates` | 「同一物件かもしれない」候補の記録（自動統合はしない） |
| `geocode_cache` | 住所→座標 のキャッシュ（API 呼び出し削減） |
| `notifications` | 送信済み通知（重複通知の防止） |
| `run_log` | 実行ごとのサマリ |

物件がサイトから消えても**削除せず**、`status = 'delisted'`（掲載終了）として履歴を残します。

中身を見るには [DB Browser for SQLite](https://sqlitebrowser.org/)（無料）が便利です。

---

## 通知の例

**🚨 新着物件**（100万円以下は特に目立つ色・マークで表示されます）

```
🚨 新着物件
【売買】
🔥🔥🔥 100万円以下
価格：90万円
🏠 5DK
📍 福井県あわら市舟津
🚶 あわら湯のまち駅：約850m（徒歩約11分）  ⚠️ 距離判定：要確認
掲載サイト：
・あわら市空き家バンク
・SUUMO
物件URL：
https://...
検出日時：2026/08/30
```

**💰 価格変更**

```
💰 価格変更
【売買】
旧価格：300万円
　↓
新価格：250万円   📉 値下げ（-50万円）
🎯 条件価格以下になりました
📍 福井県あわら市○○
🚶 あわら湯のまち駅：徒歩12分
掲載サイト：
・SUUMO
物件URL：
https://...
```

---

## このシステムがやらないこと

- 物件の購入・問い合わせ・見学予約・資料請求（一切しません）
- ログインが必要なページの取得
- CAPTCHA やアクセス制限の回避
- 利用規約・robots.txt で禁止されているサイトのスクレイピング
- 価格による独自の「おすすめ」判定（価格帯の色分け表示のみ）
