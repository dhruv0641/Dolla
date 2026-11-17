# Database transaction boundary

`flowx_os.db.unit_of_work(pool)` wraps one pooled async connection in one database transaction. Use it with a PostgreSQL pool that provides `connection()` and a connection that provides `transaction()`, such as psycopg 3's async pool API:

```python
async with unit_of_work(pool) as connection:
    await connection.execute("...", parameters)
```

The pool context releases the connection. The connection transaction commits if the body completes normally and rolls back when an exception escapes. Catch exceptions outside the context unless the operation intentionally handles the failure and can preserve atomicity.

The helper does not retry. Callers must use task-level idempotency and classify serialization/deadlock errors before adding bounded retries. Keep network calls and long-running work outside the transaction; persist intent and use an outbox for external side effects. This helper has unit tests against context-manager fakes; it does not claim a live database connection or validate SQL queries.
