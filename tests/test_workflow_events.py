import json
import unittest
from uuid import uuid4

from flowx_os.db import EventValidationError, WorkflowEventStore


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, query, params):
        self.calls.append((query, params))


class WorkflowEventStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_uses_parameterized_sql_and_json_payload(self):
        connection = FakeConnection()
        event = {
            "entity_type": "content",
            "entity_id": uuid4(),
            "event_name": "review.approved",
            "correlation_id": uuid4(),
            "actor": "owner:123",
            "payload": {"review_id": "r-1", "approved": True},
        }
        await WorkflowEventStore(connection).append(**event)
        sql, params = connection.calls[0]
        self.assertIn("VALUES (%s, %s, %s, %s, %s, %s::jsonb)", sql)
        self.assertNotIn("review.approved", sql)
        self.assertEqual(json.loads(params[-1]), event["payload"])

    async def test_rejects_invalid_uuid_before_database_write(self):
        connection = FakeConnection()
        with self.assertRaises(EventValidationError):
            await WorkflowEventStore(connection).append(
                entity_type="content",
                entity_id="not-a-uuid",
                event_name="changed",
                correlation_id=uuid4(),
                actor="system",
            )
        self.assertEqual(connection.calls, [])

    async def test_rejects_oversized_payload_before_database_write(self):
        connection = FakeConnection()
        with self.assertRaisesRegex(EventValidationError, "65536"):
            await WorkflowEventStore(connection).append(
                entity_type="content",
                entity_id=uuid4(),
                event_name="changed",
                correlation_id=uuid4(),
                actor="system",
                payload={"data": "x" * 65536},
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
