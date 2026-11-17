import unittest
from contextlib import asynccontextmanager

from flowx_os.db import unit_of_work


class FakeConnection:
    def __init__(self):
        self.events = []

    @asynccontextmanager
    async def transaction(self):
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection
        self.events = []

    @asynccontextmanager
    async def connection(self):
        self.events.append("acquire")
        try:
            yield self.connection_value
        finally:
            self.events.append("release")


class UnitOfWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_commits_and_releases_connection_on_success(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        async with unit_of_work(pool) as yielded:
            self.assertIs(yielded, connection)
        self.assertEqual(connection.events, ["begin", "commit"])
        self.assertEqual(pool.events, ["acquire", "release"])

    async def test_rolls_back_and_releases_connection_on_exception(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        with self.assertRaisesRegex(RuntimeError, "operation failed"):
            async with unit_of_work(pool):
                raise RuntimeError("operation failed")
        self.assertEqual(connection.events, ["begin", "rollback"])
        self.assertEqual(pool.events, ["acquire", "release"])


if __name__ == "__main__":
    unittest.main()
