import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Load .env if exists (local dev)
    load_dotenv()
except ImportError:
    pass

# Also support webhook/webhook.txt for local dev (gitignored)
_webhook_file = Path(__file__).parent.parent / "webhook" / "webhook.txt"
if _webhook_file.exists() and not os.getenv("DISCORD_WEBHOOK_URL"):
    try:
        txt = _webhook_file.read_text(encoding="utf-8").strip()
        # Tolerate missing "://" (e.g. "httpsdiscord.com/...")
        if "discord.com/api/webhooks" in txt:
            if txt.startswith("httpsdiscord.com"):
                txt = txt.replace("httpsdiscord.com", "https://discord.com", 1)
            elif txt.startswith("https:/discord.com"):
                txt = txt.replace("https:/discord.com", "https://discord.com", 1)
            if txt.startswith("https://"):
                os.environ["DISCORD_WEBHOOK_URL"] = txt
    except Exception:
        pass

DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

# Thresholds (fraction, e.g. 0.05 = 5%)
THRESHOLD_5M: float = float(os.getenv("THRESHOLD_5M", "0.05"))
THRESHOLD_15M: float = float(os.getenv("THRESHOLD_15M", "0.08"))
THRESHOLD_PREVDAY: float = float(os.getenv("THRESHOLD_PREVDAY", "0.10"))

COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "300"))

# --- Trigger mode ---
# price: 従来の価格変動のみ / liquidation: 清算のみ / both: どちらかが閾値超えで発火
TRIGGER_MODE: str = os.getenv("TRIGGER_MODE", "both").lower()  # price|liquidation|both
if TRIGGER_MODE not in ("price", "liquidation", "both"):
    raise ValueError(f"Unknown TRIGGER_MODE '{TRIGGER_MODE}' — use price|liquidation|both")

# --- Liquidation thresholds ---
# 方式: OIドロップ(USD)の閾値 + OIドロップ率の閾値 のOR。Actionsの5分pollで取得可能なmetaAndAssetCtxs.openInterestを監視。
# 単発: 5分で失われたOI(清算推定)が閾値を超えたら即通知
# ローリング: 15分累積も同様
LIQ_ENABLED: bool = os.getenv("LIQ_ENABLED", "1").lower() not in ("0", "false", "no")
LIQ_SINGLE_USD: float = float(os.getenv("LIQ_SINGLE_USD", "0"))  # 0なら銘柄別デフォルトを使用
LIQ_5M_USD: float = float(os.getenv("LIQ_5M_USD", "0"))
LIQ_15M_USD: float = float(os.getenv("LIQ_15M_USD", "0"))
# OIドロップ率閾値 (0.05=5%ドロップで発火)。出来高薄い銘柄でも検知できるようUSDとOR
LIQ_DROP_PCT_5M: float = float(os.getenv("LIQ_DROP_PCT_5M", "0.04"))  # 4%
LIQ_DROP_PCT_15M: float = float(os.getenv("LIQ_DROP_PCT_15M", "0.07"))  # 7%

# 銘柄別デフォルト (USD)。出来高・OI規模でスケール。未指定銘柄は汎用 50k/150k
_LIQ_DEFAULTS_SINGLE: dict[str, float] = {
    "HYPE": 25000,
    "SOL": 50000,
    "NVDA": 50000,
    "MU": 75000,
    "SNDK": 100000,
    "SKHYNIX": 75000,
}
_LIQ_DEFAULTS_5M: dict[str, float] = {
    "HYPE": 100000,
    "SOL": 200000,
    "NVDA": 150000,
    "MU": 250000,
    "SNDK": 300000,
    "SKHYNIX": 250000,
}
_LIQ_DEFAULTS_15M: dict[str, float] = {
    "HYPE": 200000,
    "SOL": 350000,
    "NVDA": 300000,
    "MU": 450000,
    "SNDK": 600000,
    "SKHYNIX": 450000,
}

def liq_threshold_single(symbol: str) -> float:
    if LIQ_SINGLE_USD > 0:
        return LIQ_SINGLE_USD
    return _LIQ_DEFAULTS_SINGLE.get(symbol, 50000)

def liq_threshold_5m(symbol: str) -> float:
    if LIQ_5M_USD > 0:
        return LIQ_5M_USD
    return _LIQ_DEFAULTS_5M.get(symbol, 150000)

def liq_threshold_15m(symbol: str) -> float:
    if LIQ_15M_USD > 0:
        return LIQ_15M_USD
    return _LIQ_DEFAULTS_15M.get(symbol, 300000)

# --- Symbol mapping ---
# Display symbol -> (dex, hl_name)
# HYPE / SOL are on main perp dex (""); equities are on xyz dex.
# SKHYNIX display maps to Hyperliquid's SKHY ticker.
SYMBOL_TO_HL: dict[str, tuple[str, str]] = {
    "HYPE": ("", "HYPE"),
    "NVDA": ("xyz", "xyz:NVDA"),
    "SNDK": ("xyz", "xyz:SNDK"),
    "SKHYNIX": ("xyz", "xyz:SKHY"),
    "SOL": ("", "SOL"),
    "MU": ("xyz", "xyz:MU"),
}

# Allow override via env: SYMBOLS="HYPE,SOL,NVDA,..."
_env_symbols = os.getenv("SYMBOLS", "")
if _env_symbols.strip():
    SYMBOLS: list[str] = [s.strip().upper() for s in _env_symbols.split(",") if s.strip()]
else:
    SYMBOLS: list[str] = list(SYMBOL_TO_HL.keys())

# Validate that all requested symbols have a mapping
for _s in SYMBOLS:
    if _s not in SYMBOL_TO_HL:
        raise ValueError(f"Unknown symbol '{_s}' — no Hyperliquid mapping in SYMBOL_TO_HL")

# State file path (committed to repo)
STATE_PATH: Path = Path(os.getenv("STATE_PATH", str(Path(__file__).parent.parent / ".state" / "hype_state.json")))

# Hyperliquid API
HL_API_URL: str = os.getenv("HL_API_URL", "https://api.hyperliquid.xyz/info")

# Polling (for local continuous mode, not used in Actions)
POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "30"))
