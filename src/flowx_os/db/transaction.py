"""Driver-neutral async transaction boundary for PostgreSQL connection pools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol


class TransactionConnection(Protocol):
    """Minimum shape required from an async PostgreSQL connection."""

    def transaction(self) -> AbstractAsyncContextManager[object]: ...


class ConnectionPool(Protocol):
    """Minimum shape required from a pool such as psycopg_pool.AsyncConnectionPool."""

    def connection(self) -> AbstractAsyncContextManager[TransactionConnection]: ...


@asynccontextmanager
async def unit_of_work(pool: ConnectionPool) -> AsyncIterator[TransactionConnection]:
    """Lease one connection and commit on success or roll back on exceptions.

    Pool context managers own connection release. Transaction context managers
    own commit/rollback. No retries are performed because callers must first
    establish idempotency and classify database errors at the operation layer.
    """
    async with pool.connection() as connection:
        async with connection.transaction():
            yield connection
