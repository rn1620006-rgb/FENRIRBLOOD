import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
ON_VERCEL = bool(os.getenv("VERCEL"))
# IMPORTANT: Vercel /tmp storage is TEMPORARY, NEVER durable.
# Write operations are disabled on Vercel until a persistent database is implemented.
DB_PATH = Path(os.getenv("FENRIR_DB_PATH", "/tmp/fenrirblood.sqlite3" if ON_VERCEL else str(ROOT / "data" / "fenrirblood.sqlite3"))).resolve()
SECURE_COOKIES = os.getenv("FENRIR_SECURE_COOKIES", "true" if ON_VERCEL else "false").lower() == "true"
PUBLIC_URL = os.getenv("FENRIR_PUBLIC_URL", "https://fenrirblood.vercel.app" if ON_VERCEL else "http://127.0.0.1:8000").rstrip("/")
ALLOWED_ORIGINS = set(filter(None, (x.strip().rstrip("/") for x in os.getenv("FENRIR_ALLOWED_ORIGINS", "").split(","))))
SESSION_DAYS = max(1, min(int(os.getenv("FENRIR_SESSION_DAYS", "7")), 30))
