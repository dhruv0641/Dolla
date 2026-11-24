#!/usr/bin/env python3
"""Initialize local-only secret files in a Docker-managed volume."""

import secrets
from pathlib import Path


ROOT = Path("/run/local-secrets")
LEGACY_ROOT = Path("/run/legacy-secrets")
SECRETS = (
    (ROOT / "postgres_admin" / "password", LEGACY_ROOT / "postgres_admin_password"),
    (ROOT / "postgres_runtime" / "password", LEGACY_ROOT / "postgres_runtime_password"),
    (ROOT / "auth_signing" / "key", LEGACY_ROOT / "auth_signing_key"),
)


def main() -> int:
    for path, legacy_path in SECRETS:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            if not path.is_file() or path.is_symlink() or path.stat().st_size < 32:
                raise RuntimeError(f"invalid existing local secret envelope: {path.parent.name}")
            continue
        if legacy_path.is_file() and not legacy_path.is_symlink():
            value = legacy_path.read_text(encoding="utf-8").strip()
            if len(value) < 32 or any(char in value for char in "\r\n\x00"):
                raise RuntimeError(f"invalid legacy secret envelope: {path.parent.name}")
        else:
            value = secrets.token_hex(32)
        path.write_text(value, encoding="utf-8")
        path.chmod(0o444)
    print("Local secret volume initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
