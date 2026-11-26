"""Memory-efficient multi-service launcher for single-container Render deployments.

Each microservice lives in its own directory with its own top-level ``app``
package, so they cannot share one interpreter. Running them as independent
``uvicorn`` processes duplicates ~90 MB of library imports per service, which
exhausts Render's 512 MB free tier.

This launcher imports the heavy third-party libraries ONCE, then ``fork()``s a
child per service. Children share the preloaded library pages copy-on-write
and only pay for their own application code. Crashed children are restarted
with backoff; SIGTERM/SIGINT are forwarded for graceful shutdown.

Usage:
    python render_launcher.py name:directory:host:port [name:directory:host:port ...]
"""

from __future__ import annotations

import gc
import importlib
import os
import signal
import sys
import time

# Libraries common to every service. Import failures are tolerated so a
# service that lacks an optional dependency still boots.
_PRELOAD_MODULES = (
    "asyncio",
    "json",
    "logging",
    "uuid",
    "pydantic",
    "pydantic_settings",
    "starlette.applications",
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.middleware.gzip",
    "uvicorn",
    "uvicorn.config",
    "uvicorn.server",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.loops.uvloop",
    "httpx",
    "sqlalchemy",
    "sqlalchemy.ext.asyncio",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "asyncpg",
    "redis.asyncio",
    "aiokafka",
    "jwt",
)

_MAX_BACKOFF_SECONDS = 30.0
_STABLE_RUNTIME_SECONDS = 60.0


def _log(message: str) -> None:
    print(f"[launcher] {message}", flush=True)


def _preload() -> None:
    for module_name in _PRELOAD_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - optional deps
            _log(f"preload skipped {module_name}: {exc}")
    gc.collect()
    # Move everything allocated so far into the permanent generation so the
    # cyclic GC never touches (and therefore never dirties) shared pages.
    if hasattr(gc, "freeze"):
        gc.freeze()


def normalize_database_url(url: str) -> str:
    """Convert provider URLs (Neon, Render, Supabase) into SQLAlchemy asyncpg form.

    * ``postgres://`` / ``postgresql://`` -> ``postgresql+asyncpg://``
    * libpq-only query params (``sslmode``, ``channel_binding``) are not
      understood by asyncpg and crash the first query, so ``sslmode`` is
      translated to asyncpg's ``ssl`` and ``channel_binding`` is dropped.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break
    if not url.startswith("postgresql+asyncpg://"):
        return url

    parts = urlsplit(url)
    params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        if key == "sslmode":
            key, value = "ssl", ("require" if value in {"verify-ca", "verify-full"} else value)
        params.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(params)))


def resolve_database_url(name: str, db_name: str) -> str | None:
    """Pick the database URL for one service.

    Precedence:
      1. ``<SERVICE>_DATABASE_URL`` e.g. ``IDENTITY_DATABASE_URL``
      2. ``POSTGRES_HOST``/``POSTGRES_USER``/``POSTGRES_PASSWORD`` + per-service db name
         (matches ``scripts/migrate_all_neon.py``)
      3. A shared ``DATABASE_URL`` (all services in one database)
    """
    from urllib.parse import quote

    prefix = name.replace("-service", "").replace("-", "_").upper()
    explicit = os.environ.get(f"{prefix}_DATABASE_URL")
    if explicit:
        return normalize_database_url(explicit)

    host = os.environ.get("POSTGRES_HOST")
    if host and db_name:
        user = quote(os.environ.get("POSTGRES_USER", "postgres"), safe="")
        password = quote(os.environ.get("POSTGRES_PASSWORD", ""), safe="")
        port = os.environ.get("POSTGRES_PORT", "5432")
        ssl_param = os.environ.get("POSTGRES_SSL_PARAM", "")
        if ssl_param and not ssl_param.startswith("?"):
            ssl_param = "?" + ssl_param
        return normalize_database_url(
            f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}{ssl_param}"
        )

    shared = os.environ.get("DATABASE_URL")
    return normalize_database_url(shared) if shared else None


def _prepare_environment(name: str, db_name: str) -> None:
    if db_name:
        url = resolve_database_url(name, db_name)
        if url:
            os.environ["DATABASE_URL"] = url
        else:
            _log(f"WARNING: no database configured for {name}; DB endpoints will fail")
    # Small pools: many services share one free-tier Postgres connection limit.
    for key, default in (
        ("DB_POOL_SIZE", "3"),
        ("DATABASE_POOL_SIZE", "3"),
        ("DB_MAX_OVERFLOW", "2"),
        ("DATABASE_MAX_OVERFLOW", "2"),
    ):
        os.environ.setdefault(key, os.environ.get(f"RENDER_{key}", default))


def _run_migrations(name: str, directory: str) -> None:
    if os.environ.get("RUN_MIGRATIONS", "true").lower() not in {"1", "true", "yes"}:
        return
    if not os.path.exists(os.path.join(directory, "alembic.ini")):
        return
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql+asyncpg://"):
        return
    import subprocess

    _log(f"running migrations for {name}")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": directory},
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        # Do not crash-loop the service: log and continue so health checks and
        # non-DB endpoints still work while the operator fixes the database.
        _log(f"migrations FAILED for {name}:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}")
    else:
        _log(f"migrations complete for {name}")


def _run_service(name: str, directory: str, host: str, port: int, db_name: str = "") -> None:
    """Child process body: switch into the service directory and serve it."""
    os.chdir(directory)
    sys.path.insert(0, directory)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _prepare_environment(name, db_name)
    _run_migrations(name, directory)

    import uvicorn

    extra: dict[str, object] = {}
    if host == "0.0.0.0":
        extra = {"proxy_headers": True, "forwarded_allow_ips": "*"}

    _log(f"starting {name} on {host}:{port} (pid {os.getpid()})")
    try:
        uvicorn.run("app.main:app", host=host, port=port, workers=1, log_level="info", **extra)
    except BaseException as exc:
        _log(f"{name} crashed: {exc!r}")
        os._exit(1)
    os._exit(0)


def _parse_specs(argv: list[str]) -> list[tuple[str, str, str, int, str]]:
    specs = []
    for raw in argv:
        parts = raw.split(":")
        try:
            if len(parts) == 4:
                parts.append("")
            name, directory, host, port, db_name = parts
            if port.startswith("$"):
                port = os.environ.get(port[1:], "8000")
            specs.append((name, directory, host, int(port), db_name))
        except ValueError:
            raise SystemExit(
                f"Invalid service spec {raw!r}; expected name:dir:host:port[:db_name]"
            )
    if not specs:
        raise SystemExit(__doc__)
    return specs


def main() -> None:
    specs = _parse_specs(sys.argv[1:])
    _preload()

    children: dict[int, tuple[str, str, str, int, str]] = {}
    started_at: dict[str, float] = {}
    backoff: dict[str, float] = {spec[0]: 1.0 for spec in specs}
    shutting_down = False

    def spawn(spec: tuple[str, str, str, int, str]) -> None:
        pid = os.fork()
        if pid == 0:
            _run_service(*spec)
        children[pid] = spec
        started_at[spec[0]] = time.monotonic()

    def handle_shutdown(signum, _frame) -> None:
        nonlocal shutting_down
        shutting_down = True
        _log(f"received signal {signum}; stopping {len(children)} services")
        for pid in list(children):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Start internal services first; the public-facing service (host 0.0.0.0)
    # is listed last by convention.
    for spec in specs:
        spawn(spec)

    deadline: float | None = None
    while children:
        try:
            pid, status = os.waitpid(-1, 0 if not shutting_down else os.WNOHANG)
        except ChildProcessError:
            break
        except InterruptedError:
            continue

        if pid == 0:
            if deadline is None:
                deadline = time.monotonic() + 20
            if time.monotonic() > deadline:
                for remaining in list(children):
                    try:
                        os.kill(remaining, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            time.sleep(0.2)
            continue

        spec = children.pop(pid, None)
        if spec is None or shutting_down:
            continue

        name = spec[0]
        runtime = time.monotonic() - started_at.get(name, 0.0)
        if runtime > _STABLE_RUNTIME_SECONDS:
            backoff[name] = 1.0
        delay = backoff[name]
        backoff[name] = min(delay * 2, _MAX_BACKOFF_SECONDS)
        _log(f"{name} exited (status {status}); restarting in {delay:.0f}s")
        time.sleep(delay)
        if not shutting_down:
            spawn(spec)

    _log("all services stopped")


if __name__ == "__main__":
    main()
