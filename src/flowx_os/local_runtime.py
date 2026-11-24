"""Fail-closed local runtime bootstrap for the Compose development profile."""

from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI

from flowx_os.auth.tokens import TokenVerifier


class LocalRuntimeConfigurationError(RuntimeError):
    """Raised before startup when local runtime inputs are unsafe or incomplete."""


def read_file_secret(reference: str | None) -> str:
    """Resolve only container-mounted secret files under ``/run/secrets``."""
    prefix = "secretref://file"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise LocalRuntimeConfigurationError("a secretref://file reference is required")
    path = PurePosixPath(reference[len(prefix):])
    if not path.is_absolute() or path.parts[:3] != ("/", "run", "secrets") or ".." in path.parts:
        raise LocalRuntimeConfigurationError("local secret references must stay under /run/secrets")
    file_path = Path(str(path))
    if not file_path.is_file() or file_path.is_symlink():
        raise LocalRuntimeConfigurationError("referenced local secret file is unavailable")
    value = file_path.read_text(encoding="utf-8").strip()
    if not 32 <= len(value) <= 512 or any(char in value for char in "\r\n\x00"):
        raise LocalRuntimeConfigurationError("referenced local secret has an invalid envelope")
    return value


def _required(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or not value.strip():
        raise LocalRuntimeConfigurationError(f"{name} is required")
    return value.strip()


def database_conninfo(*, admin: bool = False) -> str:
    # Keep the optional native database driver out of module import so the
    # non-runtime API shell and configuration tests work on locked-down hosts.
    from psycopg.conninfo import make_conninfo

    suffix = "ADMIN" if admin else "RUNTIME"
    password = read_file_secret(_required(f"FLOWX_DATABASE_{suffix}_CREDENTIALS_REF"))
    return make_conninfo(
        host=_required("FLOWX_DATABASE_HOST", "db"),
        port=_required("FLOWX_DATABASE_PORT", "5432"),
        dbname=_required("FLOWX_DATABASE_NAME", "flowx"),
        user=_required(f"FLOWX_DATABASE_{suffix}_USER", "postgres" if admin else "flowx_runtime"),
        password=password,
        connect_timeout="5",
        application_name="flowx-local",
    )


def create_local_app() -> FastAPI:
    """Build the local API with live PostgreSQL, auth and managed-storage checks."""
    from psycopg_pool import AsyncConnectionPool

    from flowx_os.api.main import create_app

    pool = AsyncConnectionPool(conninfo=database_conninfo(), min_size=1, max_size=6, open=False)
    storage_root = Path(_required("FLOWX_STORAGE_ROOT", "/app/data")).resolve()
    token_key = read_file_secret(_required("FLOWX_AUTH_SIGNING_KEY_REF")).encode("utf-8")
    verifier = TokenVerifier(
        token_key,
        issuer=_required("FLOWX_AUTH_ISSUER", "flowx-local"),
        audience=_required("FLOWX_AUTH_AUDIENCE", "flowx-api"),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        storage_root.mkdir(parents=True, exist_ok=True)
        await pool.open(wait=True, timeout=15)
        try:
            yield
        finally:
            await pool.close()

    async def database_ready() -> bool:
        try:
            async with pool.connection(timeout=3) as connection:
                cursor = await connection.execute("SELECT 1")
                return await cursor.fetchone() == (1,)
        except Exception:
            return False

    def storage_ready() -> bool:
        try:
            storage_root.mkdir(parents=True, exist_ok=True)
            probe = storage_root / ".readiness"
            probe.touch(exist_ok=True)
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    return create_app(
        readiness_checks={
            "database": database_ready,
            "ffmpeg": lambda: shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
            "managed_storage": storage_ready,
        },
        token_verifier=verifier,
        database_pool=pool,
        storage_root=storage_root,
        lifespan=lifespan,
    )
