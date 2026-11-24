#!/usr/bin/env python3
"""Exercise local readiness, persistence, owner isolation and worker replay."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from uuid import uuid4

from psycopg_pool import AsyncConnectionPool

from flowx_os.db.outbox import enqueue_job
from flowx_os.db.transaction import unit_of_work
from flowx_os.local_runtime import database_conninfo, read_file_secret


def _segment(value: object) -> str:
    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(subject: str) -> str:
    key = read_file_secret(os.environ.get("FLOWX_AUTH_SIGNING_KEY_REF")).encode("utf-8")
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims = _segment({
        "sub": subject,
        "roles": ["operator"],
        "iss": os.environ.get("FLOWX_AUTH_ISSUER", "flowx-local"),
        "aud": os.environ.get("FLOWX_AUTH_AUDIENCE", "flowx-api"),
        "exp": int(time.time()) + 300,
    })
    signature = base64.urlsafe_b64encode(
        hmac.new(key, f"{header}.{claims}".encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    return f"{header}.{claims}.{signature}"


def _request(base_url: str, method: str, path: str, *, token: str | None = None,
             body: dict[str, object] | None = None) -> tuple[int, object]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}", method=method, headers=headers,
        data=None if body is None else json.dumps(body).encode("utf-8"),
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())
    with response:
        return response.status, json.loads(response.read())


async def main() -> int:
    base_url = os.environ.get("FLOWX_API_BASE_URL", "http://api:8000")
    owner_a, owner_b = f"smoke-a-{uuid4()}", f"smoke-b-{uuid4()}"
    status, ready = _request(base_url, "GET", "/readyz")
    if status != 200 or not isinstance(ready, dict) or ready.get("status") != "ready":
        raise RuntimeError("API did not report ready")
    first, second = _token(owner_a), _token(owner_b)
    status, brand = _request(
        base_url, "POST", "/api/v1/brands", token=first,
        body={"name": f"Local smoke {uuid4()}"},
    )
    if status != 201 or not isinstance(brand, dict):
        detail = brand.get("detail") if isinstance(brand, dict) else "invalid_response"
        raise RuntimeError(f"brand creation failed: HTTP {status} ({detail})")
    brand_id = brand["id"]
    status, content = _request(
        base_url, "POST", f"/api/v1/brands/{brand_id}/content", token=first,
        body={"title": "Safe local lifecycle", "idea_text": "Local fake-provider evidence only"},
    )
    if status != 201 or not isinstance(content, dict):
        raise RuntimeError("content creation failed")
    content_id = content["id"]
    status, _ = _request(
        base_url, "POST", f"/api/v1/brands/{brand_id}/content/{content_id}/transition",
        token=first, body={"target_status": "RESEARCHED"},
    )
    if status != 200:
        raise RuntimeError("content transition failed")
    status, _ = _request(
        base_url, "GET", f"/api/v1/brands/{brand_id}/content", token=second
    )
    if status != 404:
        raise RuntimeError("owner isolation check failed")
    status, listed = _request(
        base_url, "GET", f"/api/v1/brands/{brand_id}/content", token=first
    )
    if status != 200 or not isinstance(listed, list) or listed[0]["status"] != "RESEARCHED":
        raise RuntimeError("persisted transition was not visible")

    pool = AsyncConnectionPool(conninfo=database_conninfo(), min_size=1, max_size=1, open=False)
    await pool.open(wait=True, timeout=10)
    try:
        key, correlation = uuid4(), uuid4()
        async with unit_of_work(pool) as connection:
            blocked_job = await enqueue_job(
                connection, idempotency_key=uuid4(), event_name="external.never",
                correlation_id=correlation, payload={"content_id": content_id},
            )
            first_job = await enqueue_job(
                connection, idempotency_key=key, event_name="local.smoke",
                correlation_id=correlation, payload={"content_id": content_id},
            )
            replayed_job = await enqueue_job(
                connection, idempotency_key=key, event_name="local.smoke",
                correlation_id=correlation, payload={"content_id": content_id},
            )
        if first_job != replayed_job:
            raise RuntimeError("outbox replay was not idempotent")
        for _ in range(20):
            async with pool.connection() as connection:
                row = await (await connection.execute(
                    "SELECT status FROM outbox_jobs WHERE id = %s", (first_job,)
                )).fetchone()
            if row == ("DONE",):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("local worker did not complete the smoke job")
        async with unit_of_work(pool) as connection:
            blocked_status = await (await connection.execute(
                "SELECT status FROM outbox_jobs WHERE id = %s FOR UPDATE", (blocked_job,)
            )).fetchone()
            if blocked_status != ("READY",):
                raise RuntimeError("local worker crossed its event allowlist")
            await connection.execute(
                "UPDATE outbox_jobs SET status = 'DEAD', error_detail = 'local_smoke_boundary_verified' "
                "WHERE id = %s AND status = 'READY'",
                (blocked_job,),
            )
    finally:
        await pool.close()
    print("Local smoke passed: readiness, persistence, transition, owner isolation, replay, worker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
