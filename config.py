import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# How long ephemeral messages stay visible before auto-deletion (in seconds)
EPHEMERAL_DELETE_DELAY = 5

# Bot admins (Discord user IDs) - these users have all permissions
# Set as comma-separated IDs in .env, e.g.: ADMIN_IDS=123456789,987654321
_admin_ids_str = os.getenv("ADMIN_IDS", "").strip("[]")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip()]

# API server settings
API_ENABLED = os.getenv("API_ENABLED", "true").lower() == "true"
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

# Web URL for quote links (e.g., "https://quotes.example.com")
WEB_URL = os.getenv("WEB_URL", "")
