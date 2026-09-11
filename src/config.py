import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_webhook_file = Path(__file__).parent.parent / "webhook" / "webhook.txt"
if _webhook_file.exists() and not os.getenv("DISCORD_WEBHOOK_URL"):
    try:
        _url = _webhook_file.read_text(encoding="utf-8").strip()
        if "discord.com/api/webhooks" in _url:
            _url = _url.replace("httpsdiscord.com", "https://discord.com", 1)
            _url = _url.replace("https:/discord.com", "https://discord.com", 1)
            if _url.startswith("https://"):
                os.environ["DISCORD_WEBHOOK_URL"] = _url
    except OSError:
        pass

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
HL_API_URL = os.getenv("HL_API_URL", "https://api.hyperliquid.xyz/info")
STATE_PATH = Path(os.getenv("STATE_PATH", str(Path(__file__).parent.parent / ".state" / "hype_state.json")))

# Empty string denotes Hyperliquid's main perpetual DEX. `xyz` is trade.xyz.
MONITORED_DEXES = tuple(d.strip() for d in os.getenv("MONITORED_DEXES", ",xyz").split(","))
# Optional comma-separated ticker filter. Empty means every market passing liquidity filters.
SYMBOLS = {s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()}
MIN_OPEN_INTEREST_USD = float(os.getenv("MIN_OPEN_INTEREST_USD", "1000000"))
MIN_DAY_VOLUME_USD = float(os.getenv("MIN_DAY_VOLUME_USD", "1000000"))
STATE_RETENTION_SECONDS = int(os.getenv("STATE_RETENTION_SECONDS", str(7 * 24 * 3600)))

THRESHOLD_5M = float(os.getenv("THRESHOLD_5M", "0.05"))
THRESHOLD_15M = float(os.getenv("THRESHOLD_15M", "0.08"))
THRESHOLD_PREVDAY = float(os.getenv("THRESHOLD_PREVDAY", "0.10"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))
TRIGGER_MODE = os.getenv("TRIGGER_MODE", "both").lower()
if TRIGGER_MODE not in ("price", "liquidation", "both"):
    raise ValueError("TRIGGER_MODE must be price, liquidation, or both")

LIQ_ENABLED = os.getenv("LIQ_ENABLED", "1").lower() not in ("0", "false", "no")
LIQ_SINGLE_USD = float(os.getenv("LIQ_SINGLE_USD", "50000"))
LIQ_5M_USD = float(os.getenv("LIQ_5M_USD", "150000"))
LIQ_15M_USD = float(os.getenv("LIQ_15M_USD", "300000"))
LIQ_DROP_PCT_5M = float(os.getenv("LIQ_DROP_PCT_5M", "0.04"))
LIQ_DROP_PCT_15M = float(os.getenv("LIQ_DROP_PCT_15M", "0.07"))

# A Discord webhook accepts at most 10 embeds per message. The cap bounds burst volume.
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "20"))
MAX_WEBHOOK_RETRIES = int(os.getenv("MAX_WEBHOOK_RETRIES", "5"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
