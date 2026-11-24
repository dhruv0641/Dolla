#!/usr/bin/env python3
"""Apply ordered, checksummed PostgreSQL migrations for the local profile."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import psycopg
from psycopg import sql

from flowx_os.local_runtime import database_conninfo, read_file_secret


ROOT = Path(__file__).resolve().parents[1]
LOCK_ID = 7720241124


def main() -> int:
    runtime_password = read_file_secret(os.environ.get("FLOWX_DATABASE_RUNTIME_CREDENTIALS_REF"))
    migrations = sorted((ROOT / "migrations").glob("*.sql"))
    if not migrations:
        raise RuntimeError("no migrations found")
    with psycopg.connect(database_conninfo(admin=True), autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS flowx_schema_migrations (
                       migration_name text PRIMARY KEY,
                       sha256_hex text NOT NULL CHECK (sha256_hex ~ '^[0-9a-f]{64}$'),
                       applied_at timestamptz NOT NULL DEFAULT now()
                   )"""
            )
            for migration in migrations:
                content = migration.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                existing = connection.execute(
                    "SELECT sha256_hex FROM flowx_schema_migrations WHERE migration_name = %s",
                    (migration.name,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != digest:
                        raise RuntimeError(f"migration checksum changed: {migration.name}")
                    continue
                with connection.transaction():
                    connection.execute(content.decode("utf-8"))
                    connection.execute(
                        "INSERT INTO flowx_schema_migrations (migration_name, sha256_hex) VALUES (%s, %s)",
                        (migration.name, digest),
                    )
            connection.execute(
                """DO $$ BEGIN
                       IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowx_runtime') THEN
                         CREATE ROLE flowx_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
                       END IF;
                   END $$"""
            )
            connection.execute(
                sql.SQL("ALTER ROLE flowx_runtime PASSWORD {}").format(sql.Literal(runtime_password))
            )
            connection.execute("GRANT CONNECT ON DATABASE flowx TO flowx_runtime")
            connection.execute("GRANT USAGE ON SCHEMA public TO flowx_runtime")
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE ON brands, content_items, workflow_events, outbox_jobs TO flowx_runtime"
            )
            connection.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO flowx_runtime")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    print(f"Applied or verified {len(migrations)} migrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
