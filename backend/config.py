import os
import secrets
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Application Configuration
APP_NAME = "Lab Data Upload System"
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# JWT signing key. Never fall back to a predictable value: a guessable key lets
# anyone forge tokens for any user/role. If it is missing or set to a known
# insecure placeholder, generate a random ephemeral key (JWTs are then
# invalidated on restart) and warn loudly.
_INSECURE_SECRETS = {
    "",
    "your-secret-key-change-in-production",
    "dev-secret-key-change-in-production",
}
SECRET_KEY = (os.getenv("SECRET_KEY") or "").strip()
if SECRET_KEY in _INSECURE_SECRETS:
    SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning(
        "SECRET_KEY is not set (or uses an insecure default). A random ephemeral "
        "key was generated; all issued tokens will be invalidated on restart. "
        "Set a strong SECRET_KEY in the environment for production."
    )

# Default upload interval in minutes
DEFAULT_UPLOAD_INTERVAL = int(os.getenv("DEFAULT_UPLOAD_INTERVAL", "240"))  # 4 hours = 240 minutes

# CORS Configuration
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8001",
    "http://localhost:8081",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8081",
]

# Allow any GitHub Codespaces domain (for dynamic tunnels)
ALLOWED_ORIGINS_PATTERN = r"https://[a-z0-9\-]+\-800[01]\.app\.github\.dev"
