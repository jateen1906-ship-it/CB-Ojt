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
        "content": "# CodeBridge Workspace\n\nProject files loaded successfully.\n",
    },
    "app/main.py": {
        "path": "app/main.py",
        "language": "python",
        "content": "from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'status': 'healthy'}\n",
    },
    "app/webhooks.py": {
        "path": "app/webhooks.py",
        "language": "python",
        "content": "import hmac, hashlib\n\nSECRET = b'whsec_demo_key_123'\n\ndef verify_signature(payload: bytes, signature: str) -> bool:\n    expected = hmac.new(SECRET, payload, hashlib.sha256).hexdigest()\n    return hmac.compare_digest(expected, signature)\n",
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
