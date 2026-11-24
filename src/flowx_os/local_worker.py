"""Bounded local-only outbox worker used by the Compose verification profile."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from flowx_os.db.outbox import lease_due_jobs
from flowx_os.db.transaction import unit_of_work
from flowx_os.local_runtime import database_conninfo
from flowx_os.workflow.dispatcher import LeasedJob, OutboxDispatcher


WORKER_ID = "flowx-local-worker"


async def _local_smoke_handler(connection, job: LeasedJob) -> None:
    await connection.execute("SELECT %s::uuid", (job.id,))


async def run() -> None:
    pool = AsyncConnectionPool(conninfo=database_conninfo(), min_size=1, max_size=2, open=False)
    health_file = Path(os.environ.get("FLOWX_WORKER_HEALTH_FILE", "/tmp/flowx-worker-ready"))
    await pool.open(wait=True, timeout=15)
    dispatcher = OutboxDispatcher(pool, {"local.smoke": _local_smoke_handler})
    try:
        while True:
            async with unit_of_work(pool) as connection:
                rows = await lease_due_jobs(
                    connection, worker_id=WORKER_ID, now=datetime.now(timezone.utc), limit=10,
                    allowed_event_names=("local.smoke",),
                )
            for row in rows:
                await dispatcher.dispatch(LeasedJob.from_row(row), worker_id=WORKER_ID)
            health_file.touch(exist_ok=True)
            await asyncio.sleep(1)
    finally:
        health_file.unlink(missing_ok=True)
        await pool.close()


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
