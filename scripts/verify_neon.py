"""Verify all tables in the 12 CodeBridge databases."""
import asyncio
import os
from pathlib import Path
import asyncpg

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env
env_file = BASE_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

HOST = os.getenv("POSTGRES_HOST", "localhost")
PORT = os.getenv("POSTGRES_PORT", "5432")
USER = os.getenv("POSTGRES_USER", "postgres")
PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
SSL_PARAM = os.getenv("POSTGRES_SSL_PARAM", "")

SERVICES = [
    ("identity-service", "codebridge_identity"),
    ("project-service", "codebridge_project"),
    ("github-service", "codebridge_github"),
    ("code-context-service", "codebridge_code_context"),
    ("workspace-service", "codebridge_workspace"),
    ("review-service", "codebridge_review"),
    ("verification-service", "codebridge_verification"),
    ("payment-service", "codebridge_payment"),
    ("notification-service", "codebridge_notification"),
    ("admin-service", "codebridge_admin"),
    ("audit-service", "codebridge_audit"),
    ("observability-service", "codebridge_observability"),
]

async def verify():
    print("=" * 65)
    print(f"CodeBridge 12-Service Cloud Database Verification -> {HOST}")
    print("=" * 65)
    ssl_mode = "require" if SSL_PARAM else None
    for svc, db in SERVICES:
        dsn = f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{db}"
        if ssl_mode:
            dsn += f"?ssl={ssl_mode}"
        try:
            conn = await asyncpg.connect(dsn)
            rows = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
            tables = [r['table_name'] for r in rows if r['table_name'] != 'alembic_version']
            print(f"{svc:<23} | {db:<25} | {len(tables)} tables: {', '.join(tables)}")
            await conn.close()
        except Exception as e:
            print(f"{svc:<23} | {db:<25} | ERROR: {e}")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(verify())
