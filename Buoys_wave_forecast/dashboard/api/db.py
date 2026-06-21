import json
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

PLACEHOLDER_MARKERS = (
    "@host:",
    "@host/",
    "user:pass@",
    "USER:PASSWORD@",
    "YOUR-CLUSTER",
    "YOUR_CLUSTER",
)


def _load_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    settings_file = Path(__file__).resolve().parent.parent.parent / "local.settings.json"
    if settings_file.exists():
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        url = data.get("Values", {}).get("DATABASE_URL")
        if url:
            return url

    azure_settings = Path(__file__).resolve().parent.parent.parent / "settings.json"
    if azure_settings.exists():
        data = json.loads(azure_settings.read_text(encoding="utf-8"))
        for item in data:
            if item.get("name") == "DATABASE_URL" and item.get("value"):
                return item["value"]

    return None


DATABASE_URL = _load_database_url()


def validate_database_url(url: str | None) -> str:
    if not url:
        raise ValueError(
            "DATABASE_URL is not set. Create dashboard/.env with your CockroachDB URL "
            "or set the DATABASE_URL environment variable before starting the server."
        )
    if any(marker in url for marker in PLACEHOLDER_MARKERS):
        raise ValueError(
            "DATABASE_URL is still a placeholder (user:pass@host). "
            "Use your real CockroachDB connection string for marine_forecast."
        )
    return url


def normalize_database_url(url: str) -> str:
    if "sslmode=verify-full" in url:
        return url.replace("sslmode=verify-full", "sslmode=require")
    if "sslmode=" not in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}sslmode=require"
    return url


@contextmanager
def get_db_connection():
    url = validate_database_url(DATABASE_URL)
    conn = psycopg2.connect(normalize_database_url(url))
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(query: str, params=None) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            rows = cur.fetchall()
            return [dict(row) for row in rows]
