import os
from dotenv import load_dotenv

load_dotenv()

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-project.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-anon-key")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "your-service-key")

# Direct Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# Application Configuration
APP_NAME = "Lab Data Upload System"
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

# Default upload interval in minutes
DEFAULT_UPLOAD_INTERVAL = int(os.getenv("DEFAULT_UPLOAD_INTERVAL", "240"))  # 4 hours = 240 minutes

# CORS Configuration
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    # GitHub Codespaces tunnels (specific)
    "https://scaling-robot-xr5gqg5xvvj9c9x5w-8000.app.github.dev",
    "https://scaling-robot-xr5gqg5xvvj9c9x5w-8001.app.github.dev",
]

# Allow any GitHub Codespaces domain (for dynamic tunnels) - more permissive regex
ALLOWED_ORIGINS_PATTERN = r"https://[a-z0-9\-]+\-800[01]\.app\.github\.dev"
