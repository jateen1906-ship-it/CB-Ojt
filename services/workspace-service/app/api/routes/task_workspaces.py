"""Workspaces router matching the Developer Workspace frontend contract (/api/v1/workspaces)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.dependencies import AuthContext, require_any_authenticated

router = APIRouter(prefix="/workspaces", tags=["Workspaces Frontend"])

_DEFAULT_FILES: dict[str, dict[str, Any]] = {
    "README.md": {
        "path": "README.md",
        "language": "markdown",
        "content": (
            "# Payments API\n\n"
            "Microservice handling incoming webhook deliveries from our payment processing partner.\n\n"
            "## Setup\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --port 8000\n```\n\n"
            "## Architecture\n"
            "- `app/webhooks.py`: Inbound HMAC verification and event dispatcher.\n"
            "- `app/retry.py`: Exponential backoff and retry scheduling.\n"
            "- `app/state_machine.py`: Payment lifecycle management (authorized -> held -> released).\n"
        ),
    },
    "requirements.txt": {
        "path": "requirements.txt",
        "language": "plaintext",
        "content": "fastapi==0.111.0\nuvicorn==0.30.1\npydantic==2.7.4\npytest==8.2.2\nhttpx==0.27.0\n",
    },
    "app/main.py": {
        "path": "app/main.py",
        "language": "python",
        "content": (
            "from fastapi import FastAPI, Request\n"
            "from app.webhooks import handle_webhook\n\n"
            "app = FastAPI(title='Acme Payments Webhook Service')\n\n"
            "@app.get('/health')\ndef health_check():\n    return {'status': 'healthy'}\n\n"
            "@app.post('/api/v1/webhooks/payment')\n"
            "async def webhook_endpoint(request: Request):\n"
            "    payload = await request.body()\n"
            "    signature = request.headers.get('X-Signature', '')\n"
            "    return await handle_webhook(payload, signature)\n"
        ),
    },
    "app/webhooks.py": {
        "path": "app/webhooks.py",
        "language": "python",
        "content": (
            "import hmac\nimport hashlib\nimport json\nfrom fastapi import HTTPException\n\n"
            "SECRET = b'whsec_production_demo_key_987654'\n\n"
            "def verify_signature(payload: bytes, signature: str) -> bool:\n"
            "    expected = hmac.new(SECRET, payload, hashlib.sha256).hexdigest()\n"
            "    return hmac.compare_digest(expected, signature)\n\n"
            "async def handle_webhook(payload: bytes, signature: str):\n"
            "    if not verify_signature(payload, signature):\n"
            "        raise HTTPException(status_code=400, detail='Invalid HMAC signature')\n\n"
            "    data = json.loads(payload.decode('utf-8'))\n"
            "    event_id = data.get('id')\n"
            "    return {'status': 'processed', 'eventId': event_id}\n"
        ),
    },
    "app/retry.py": {
        "path": "app/retry.py",
        "language": "python",
        "content": (
            "def calculate_retry_delay(attempt: int) -> int:\n"
            "    return min(2 ** attempt, 32)\n\n"
            "def should_retry(attempt: int) -> bool:\n"
            "    return attempt < 5\n"
        ),
    },
    "app/state_machine.py": {
        "path": "app/state_machine.py",
        "language": "python",
        "content": (
            "from enum import Enum\n\n"
            "class PaymentState(str, Enum):\n"
            "    AUTHORIZED = 'authorized'\n"
            "    HELD = 'held'\n"
            "    APPROVED = 'approved'\n"
            "    RELEASED = 'released'\n"
        ),
    },
    "tests/test_webhooks.py": {
        "path": "tests/test_webhooks.py",
        "language": "python",
        "content": (
            "import pytest\n"
            "from app.webhooks import verify_signature\n\n"
            "def test_signature_validation():\n"
            "    assert verify_signature(b'test', 'invalid') is False\n"
        ),
    },
}

_WORKSPACES: dict[str, dict[str, Any]] = {}
_WORKSPACE_FILES: dict[str, dict[str, dict[str, Any]]] = {}


def _get_or_create_workspace(task_id: str) -> dict[str, Any]:
    if task_id not in _WORKSPACES:
        _WORKSPACES[task_id] = {
            "status": "running",
            "image": "python:3.12-slim",
            "template": "FastAPI template",
            "cpu": "2 vCPU",
            "memory": "4 GB",
            "expiresAt": None,
            "repoAccess": "read-only snapshot",
            "commit": "a1b2c3d",
        }
    if task_id not in _WORKSPACE_FILES:
        _WORKSPACE_FILES[task_id] = {k: dict(v) for k, v in _DEFAULT_FILES.items()}
    return _WORKSPACES[task_id]


@router.get("/{task_id}", summary="Get workspace status for task")
async def get_task_workspace(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, Any]:
    return _get_or_create_workspace(task_id)


@router.post("/{task_id}/start", status_code=status.HTTP_200_OK, summary="Start workspace")
async def start_task_workspace(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, str]:
    ws = _get_or_create_workspace(task_id)
    ws["status"] = "running"
    return {"status": "running"}


@router.post("/{task_id}/stop", status_code=status.HTTP_200_OK, summary="Stop workspace")
async def stop_task_workspace(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, str]:
    ws = _get_or_create_workspace(task_id)
    ws["status"] = "stopped"
    return {"status": "stopped"}


@router.post("/{task_id}/reset", status_code=status.HTTP_200_OK, summary="Reset workspace")
async def reset_task_workspace(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, str]:
    ws = _get_or_create_workspace(task_id)
    ws["status"] = "running"
    _WORKSPACE_FILES[task_id] = {k: dict(v) for k, v in _DEFAULT_FILES.items()}
    return {"status": "running"}


@router.get("/{task_id}/files", summary="Get workspace file tree")
async def get_task_files(
    task_id: str,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, Any]:
    _get_or_create_workspace(task_id)
    files = _WORKSPACE_FILES.get(task_id, _DEFAULT_FILES)
    items = [
        {"path": f["path"], "type": "file", "size": len(f["content"])}
        for f in files.values()
    ]
    return {
        "commit": "a1b2c3d",
        "items": items,
        "files": items,
    }


@router.get("/{task_id}/files/content", summary="Get workspace file content")
async def get_task_file_content(
    task_id: str,
    path: str = Query(..., description="File path within workspace"),
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, Any]:
    _get_or_create_workspace(task_id)
    files = _WORKSPACE_FILES.get(task_id, _DEFAULT_FILES)
    if path in files:
        return files[path]
    return {
        "path": path,
        "language": "python" if path.endswith(".py") else "markdown" if path.endswith(".md") else "plaintext",
        "content": f"# File: {path}\n",
    }


@router.put("/{task_id}/files/content", summary="Save workspace file content")
async def save_task_file_content(
    task_id: str,
    request: Request,
    auth_ctx: AuthContext = Depends(require_any_authenticated),
) -> dict[str, Any]:
    _get_or_create_workspace(task_id)
    body = await request.json()
    file_path = body.get("path", "")
    content = body.get("content", "")
    lang = "python" if file_path.endswith(".py") else "markdown" if file_path.endswith(".md") else "plaintext"
    if task_id not in _WORKSPACE_FILES:
        _WORKSPACE_FILES[task_id] = {k: dict(v) for k, v in _DEFAULT_FILES.items()}
    _WORKSPACE_FILES[task_id][file_path] = {
        "path": file_path,
        "language": lang,
        "content": content,
    }
    return {"savedAt": datetime.now(UTC).isoformat()}
