import unittest
from pathlib import Path

from pglast import parse_sql


class MigrationSyntaxTests(unittest.TestCase):
    def test_initial_migration_parses_as_postgresql(self):
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        statements = [
            statement
            for migration in sorted(migrations.glob("*.sql"))
            for statement in parse_sql(migration.read_text(encoding="utf-8"))
        ]
        self.assertGreaterEqual(len(statements), 35)

    def test_initial_migration_contains_lineage_foreign_key(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0001_initial_schema.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("assets_source_job_fk", sql)


if __name__ == "__main__":
    unittest.main()
