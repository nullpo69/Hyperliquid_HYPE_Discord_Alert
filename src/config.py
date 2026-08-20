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

# State file path (committed to repo)
STATE_PATH: Path = Path(os.getenv("STATE_PATH", str(Path(__file__).parent.parent / ".state" / "hype_state.json")))

# Hyperliquid API
HL_API_URL: str = os.getenv("HL_API_URL", "https://api.hyperliquid.xyz/info")

# Polling (for local continuous mode, not used in Actions)
POLL_SECONDS: int = int(os.getenv("POLL_SECONDS", "30"))
