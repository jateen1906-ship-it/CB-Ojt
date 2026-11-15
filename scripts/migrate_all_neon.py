"""Run alembic migrations across all 12 CodeBridge microservices on Neon or configured database."""
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_BIN = BASE_DIR / "services" / "identity-service" / ".venv" / "Scripts" / "alembic.exe"

# Simple .env loader
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

def main():
    print("=" * 60)
    print(f"CodeBridge 12-Service Migration Runner -> Host: {HOST}")
    print("=" * 60)
    
    for service_name, db_name in SERVICES:
        service_dir = BASE_DIR / "services" / service_name
        db_url = f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{db_name}{SSL_PARAM}"
        print(f"\nRunning migration for {service_name} -> {db_name}...")
        
        env = {
            **dict(os.environ),
            "DATABASE_URL": db_url,
            "PYTHONPATH": str(service_dir),
            "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY", "dev-only-insecure-secret-key-change-before-production-32bytes"),
            "INTERNAL_SERVICE_KEY": os.getenv("INTERNAL_SERVICE_KEY", "dev-internal-service-key-change-me"),
            "VERIFICATION_SIGNING_SECRET": os.getenv("VERIFICATION_SIGNING_SECRET", "dev-verification-hmac-secret-change-me-32chars"),
            "GITHUB_TOKEN_ENCRYPTION_KEY": os.getenv("GITHUB_TOKEN_ENCRYPTION_KEY", "REVWX09OTFlfSU5TRUNVUkVfS0VZX0RPX05PVF9VU0U="),
        }
        
        cmd = [str(ALEMBIC_BIN) if ALEMBIC_BIN.exists() else "alembic", "upgrade", "head"]
        proc = subprocess.run(cmd, cwd=str(service_dir), env=env, capture_output=True, text=True)
        
        if proc.returncode == 0:
            print(f"[OK] {service_name} migrated successfully.")
        else:
            print(f"[FAIL] {service_name} (code {proc.returncode}):")
            if proc.stdout:
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr)
    
    print("\n" + "=" * 60)
    print("All service migrations completed.")
    print("=" * 60)

if __name__ == "__main__":
    main()
