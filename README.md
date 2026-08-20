# Hyperliquid HYPE Discord Alert

HYPE価格が急変動した際にDiscord Webhookへ通知するBot。Hyperliquid API (`allMids` + `metaAndAssetCtxs`) を5分ごとにGitHub Actionsでポーリングします。

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

## 状態管理

`.state/hype_state.json` はActionsが毎回 `git push` して永続化。`history` は直近4件 (20分) のみ保持。

## 構成

* `src/hyperliquid.py` — `POST https://api.hyperliquid.xyz/info {"type":"allMids"}` で `HYPE` 取得 (認証不要)。失敗時 `metaAndAssetCtxs` フォールバック。
* `src/detector.py` — 変動判定 + クールダウン
* `src/notifier.py` — Discord Embed生成 + 429リトライ
* `src/main.py` — state読み込み→fetch→detect→notify→保存

## カスタム

環境変数で上書き可: `THRESHOLD_5M`, `THRESHOLD_15M`, `THRESHOLD_PREVDAY`, `COOLDOWN_SECONDS`

## 注意

* GitHub Actionsのcronは最短5分。1分粒度が必要なら `Fly.io` / `VPS` + `--loop` へ移行。
* Webhook URLは絶対にコミットしないこと。

## 作成について

本プロジェクトは [Muse Spark 1.2 Free](https://opencode.ai) (`opencode/muse-spark-1.2-contributor-free`) を使用して作成されました。
