# Hyperliquid Discord Alert

HYPE / NVDA / SNDK / SKHYNIX (SKHY) / SOL / MU 価格が急変動した際にDiscord Webhookへ通知するBot。Hyperliquid API (`allMids` + `metaAndAssetCtxs`) を5分ごとにGitHub Actionsでポーリングします。

## 通知条件

| Window | 閾値 | 説明 |
|--------|------|------|
| 5分 | ±5% | 直前run (5分前) との比較 |
| 15分 | ±8% | 3回前run (15分前) との比較 |
| 前日比 | ±10% | `prevDayPx` との比較 |

* クールダウン: 同一方向 (上昇/下落) は5分間再通知しない。反転は即通知。
* 最大変化率のwindowを1通知に絞る。

## セットアップ

### 1. Discord Webhook

Discordチャンネル → 設定 → 連携サービス → ウェブフック → URLをコピー

### 2. GitHub Privateリポジトリ

```bash
gh repo create Hyperliquid_HYPE_Discord_Alert --private --source=. --push
```

### 3. GitHub Secretsに登録

GitHub → Settings → Secrets and variables → Actions → New secret

* `DISCORD_WEBHOOK_URL` = コピーしたWebhook URL

> ローカル開発では `webhook/webhook.txt` にURLを1行で置くか `.env` で設定。どちらも `.gitignore` で除外済み。

### 4. Actions有効化

Push後、Actionsタブで `HYPE Alert` が `*/5 * * * *` で自動実行。手動テストは `Run workflow`。

## ローカル実行

```bash
pip install -r requirements.txt
# ワンショット
python -m src.main
# 常駐ループ (30秒ポーリング)
python -m src.main --loop
```

閾値を一時的に下げてテスト:

```bash
THRESHOLD_5M=0.001 python -m src.main
```

## 対象銘柄

| 表示シンボル | Hyperliquid ticker | dex |
|---|---|---|
| HYPE | `HYPE` | `` (perp) |
| NVDA | `xyz:NVDA` | `xyz` |
| SNDK | `xyz:SNDK` | `xyz` |
| SKHYNIX | `xyz:SKHY` | `xyz` |
| SOL | `SOL` | `` (perp) |
| MU | `xyz:MU` | `xyz` |

環境変数 `SYMBOLS` で絞り込み可 (例: `SYMBOLS=HYPE,SOL`)。未指定なら全6銘柄を監視。

## 状態管理

`.state/hype_state.json` はActionsが毎回 `git push` して永続化。`symbols` ごとに `history` は直近4件 (20分) のみ保持。旧形式 (`{"history":...}`) からの自動マイグレーション対応。

## 構成

* `src/hyperliquid.py` — `POST https://api.hyperliquid.xyz/info {"type":"allMids","dex":""}` / `{"dex":"xyz"}` で全銘柄一括取得 (認証不要)。`metaAndAssetCtxs` で `prevDayPx` も取得。
* `src/detector.py` — 銘柄ごとの変動判定 + クールダウン (銘柄ごとに独立)
* `src/notifier.py` — Discord Embed生成 + 429リトライ (銘柄名をタイトル/フィールドに含む)
* `src/main.py` — state読み込み(マイグレーション)→fetch→detect(銘柄ループ)→notify→保存
* `src/config.py` — `SYMBOL_TO_HL` マッピングと `SYMBOLS` 定義

## カスタム

環境変数で上書き可: `THRESHOLD_5M`, `THRESHOLD_15M`, `THRESHOLD_PREVDAY`, `COOLDOWN_SECONDS`, `SYMBOLS`

## 注意

* GitHub Actionsのcronは最短5分。1分粒度が必要なら `Fly.io` / `VPS` + `--loop` へ移行。
* Webhook URLは絶対にコミットしないこと。

## 作成について

本プロジェクトは [Muse Spark 1.2 Free](https://opencode.ai) (`opencode/muse-spark-1.2-contributor-free`) を使用して作成されました。
