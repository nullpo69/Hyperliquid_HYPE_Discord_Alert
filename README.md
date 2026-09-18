# Hyperliquid Discord Alert

Hyperliquid main DEX と trade.xyz（Hyperliquid API上のDEX名: `xyz`）の perpetual market を監視し、価格急変またはOI急減をDiscord Webhookへ通知するBotです。GitHub Actionsでは5分ごと、ローカル常駐モードでは任意の秒数ごとに実行できます。

市場一覧は毎回Hyperliquid APIから取得します。新規上場はコードの変更なしで対象候補になります。

## 監視対象

既定値の `MONITORED_DEXES=,xyz` は次の2つを対象にします。

| DEX | 設定値 | 対象 |
| --- | --- | --- |
| Hyperliquid main | 空文字 | main perpetuals |
| trade.xyz | `xyz` | trade.xyz perpetuals |

`metaAndAssetCtxs` のperpetual universeから市場を列挙するため、spot市場は対象外です。取得したすべての市場のうち、既定では次の両方を満たすものだけを監視します。

| フィルター | 既定値 | 判定方法 |
| --- | ---: | --- |
| 最低OI | $1,000,000 | `openInterest × markPx` |
| 最低24時間想定出来高 | $1,000,000 | APIの `dayNtlVlm` |

これにより低流動性銘柄による通知の集中を抑えます。流動性を問わず全上場perpetualを監視するには、`MIN_OPEN_INTEREST_USD=0` と `MIN_DAY_VOLUME_USD=0` を設定してください。

`SYMBOLS` を指定すると、動的な全銘柄監視ではなくtickerのallow-listになります。例: `SYMBOLS=BTC,ETH,HYPE,NVDA`。

## 通知条件

`TRIGGER_MODE=both` が既定です。このモードでは、同一銘柄について同じ期間（5分または15分）の価格急変とOI急減が両方成立した場合だけ、統合された1件の通知を送ります。`price` または `liquidation` に変更すると、従来どおり片方だけを使えます。

### 価格変動

| 比較対象 | 環境変数 | 既定値 |
| --- | --- | ---: |
| 直近の実行値（約5分前） | `THRESHOLD_5M` | ±5% |
| 3回前の実行値（約15分前） | `THRESHOLD_15M` | ±8% |
| APIの前日価格 | `THRESHOLD_PREVDAY` | ±10% |

複数条件に該当した場合は、変化率が最大のものだけを通知します。`both`ではOIの5分／15分条件と同じ期間の価格条件だけが統合対象であり、前日比だけの価格変動は通知しません。同方向の価格通知は `COOLDOWN_SECONDS`（既定300秒）以内では抑制し、反対方向への転換は直ちに通知します。

### OI急減（清算推定）

HyperliquidのREST APIにグローバルな清算一覧はないため、OIの減少を清算の推定として扱います。OIはAPIのcoin建て `openInterest` を `markPx` でUSD換算して判定します。

| 比較対象 | USD条件 | 比率条件 |
| --- | ---: | ---: |
| 約5分前 | `LIQ_5M_USD`（$150,000） | `LIQ_DROP_PCT_5M`（4%） |
| 約15分前 | `LIQ_15M_USD`（$300,000） | `LIQ_DROP_PCT_15M`（7%） |

USD条件と比率条件の両方を満たす場合のみ通知します。これにより、金額だけ・率だけが大きいOI減少は通知されません。`both`では統合通知を送った時だけ、価格・OI双方のクールダウン状態を更新します。

Discord通知では、OIドロップ額とドロップ率をそれぞれ絵文字で強度表示します。統合通知の本文には、価格の現在値・比較元価格・変動率と、OI現在値・ドロップ額・ドロップ率を表示します。段階値は額が `$50k / $150k / $300k / $500k / $1m`、率が `4% / 7% / 10% / 15% / 25%` です。

> OI減少には通常の決済やポジション移動も含まれます。これは清算イベントの確定情報ではありません。

## Discordの通知制御

Discordの負荷を抑えるため、以下を実装しています。

* 1 Webhookリクエストに最大10件のEmbedをまとめて送信します。
* 1回の監視実行で送信するアラートは `MAX_ALERTS_PER_RUN`（既定20件）までです。
* 上限超過分は送信せず、最初の通知に省略件数を表示します。
* 優先順位はUSD時価総額が大きい銘柄を最優先にします。通常perpはCoinGecko、trade.xyz（HIP-3）の個別株はNasdaq公開データを使います。指数・ETF・商品・FXなど時価総額を持たないHIP-3市場、および未掲載銘柄は24時間USD取引高（`dayNtlVlm`）で補完します。同順位ではOIドロップ額、OIドロップ率、価格変動率の大きいものを優先します。
* HTTP 429時はDiscordが返す `retry_after` を待って再試行します。最大回数は `MAX_WEBHOOK_RETRIES`（既定5回）です。
* `allowed_mentions` を空にし、ticker等による意図しないメンションを防ぎます。

## API負荷

一回の実行では、各DEXに対して次の2リクエストだけを行います。

1. `allMids` — 現在価格
2. `metaAndAssetCtxs` — 上場市場、前日価格、OI、出来高

mainとtrade.xyzを監視する既定構成では、Hyperliquidへ合計4リクエスト、CoinGeckoへ時価総額取得の1リクエストを行います。trade.xyzの個別株の時価総額はNasdaqから日次キャッシュで取得します。価格、前日比、OI判定は同じ取得結果を共用します。

## セットアップ

### GitHub Actions

1. DiscordチャンネルでWebhookを作成します。
2. リポジトリの **Settings → Secrets and variables → Actions** に `DISCORD_WEBHOOK_URL` を登録します。
3. `.github/workflows/hype-alert.yml` を含めてpushします。

ワークフローはUTCで5分ごとに実行されます。stateファイルをコミットして価格・OI履歴を次回実行へ引き継ぎます。GitHub Actionsのスケジュール実行は混雑時に遅延することがあります。

### ローカル実行

```bash
pip install -r requirements.txt
Copy-Item .env.example .env
# .env にDISCORD_WEBHOOK_URLを設定
python -m src.main
```

継続実行する場合:

```bash
# 既定では30秒間隔
python -m src.main --loop
```

## 環境変数

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | 空 | Discord incoming webhook URL。 |
| `MONITORED_DEXES` | `,xyz` | 監視するDEX。空要素はmainを表す。 |
| `SYMBOLS` | 空 | 任意のticker allow-list。空なら流動性条件を満たすすべて。 |
| `MIN_OPEN_INTEREST_USD` | `1000000` | 監視対象にする最低USD OI。 |
| `MIN_DAY_VOLUME_USD` | `1000000` | 監視対象にする最低24時間想定出来高。 |
| `COINGECKO_MARKETS_URL` | `https://api.coingecko.com/api/v3/coins/markets` | 通知優先順位に使う時価総額の取得先。 |
| `COINGECKO_API_KEY` | 空 | 任意のCoinGecko APIキー。Demo APIでは`x-cg-demo-api-key`、Pro API URLでは`x-cg-pro-api-key`として送信。 |
| `NASDAQ_QUOTE_SUMMARY_URL` | Nasdaq公開API | trade.xyz個別株の時価総額取得先。`{symbol}`を含める。 |
| `HIP3_MARKET_CAP_CACHE_SECONDS` | `86400` | HIP-3個別株の時価総額を再取得する間隔。 |
| `THRESHOLD_5M` | `0.05` | 5分価格変動率。 |
| `THRESHOLD_15M` | `0.08` | 15分価格変動率。 |
| `THRESHOLD_PREVDAY` | `0.10` | 前日比変動率。 |
| `COOLDOWN_SECONDS` | `300` | 同方向通知の抑制時間。 |
| `TRIGGER_MODE` | `both` | `price` / `liquidation` / `both`。`both`は同期間の価格・OI条件を両方満たす統合通知のみ送る。 |
| `LIQ_ENABLED` | `1` | `0` / `false` / `no` でOI監視を無効化。 |
| `LIQ_5M_USD` / `LIQ_15M_USD` | `150000` / `300000` | OI急減のUSD閾値。 |
| `LIQ_DROP_PCT_5M` / `LIQ_DROP_PCT_15M` | `0.04` / `0.07` | OI急減率の閾値。 |
| `MAX_ALERTS_PER_RUN` | `20` | 1実行でDiscordへ送る最大件数。 |
| `MAX_WEBHOOK_RETRIES` | `5` | 429時の最大再試行回数。 |
| `STATE_RETENTION_SECONDS` | `604800` | 非掲載銘柄のstateを残す秒数。 |
| `POLL_SECONDS` | `30` | `--loop` 時の実行間隔（秒）。 |

## State管理

stateは `.state/hype_state.json` に保存します。市場ごとに直近4回の価格・OI履歴、および最終通知時刻を保持します。HIP-3個別株の時価総額も日次でキャッシュします。状態キーにはDEX名を含めるため同名tickerでも衝突しません。旧版の固定銘柄stateは、初回実行時にversion 2形式へリセットされます。

## 注意事項

* Webhook URLや`.env`はコミットしないでください。
* 5分ポーリングは急変の検知に最大約5分の遅延が発生します。秒単位の通知が必要な場合はWebSocketを用いる常駐方式が必要です。
* `both`では価格のみの急変・OIのみの大幅減少は通知されません。また通知上限時は、時価総額が小さい銘柄の重大イベントも後回しになります。通知量を抑えるための意図したトレードオフです。
* フィルターを0にする場合、低流動性銘柄のノイズや通知上限超過が増えます。`MAX_ALERTS_PER_RUN`を保守的に設定してください。
