# PostgreSQL backup, restore and retention

The maintenance module uses PostgreSQL's `pg_dump` custom format and requires matching `pg_restore` tools on `PATH`. Connection credentials come through a protected libpq service file (`PGSERVICEFILE`) and its password file, never command-line arguments. Backups are written to a dedicated operator-selected directory, verified with `pg_restore --list`, and accompanied by a JSON manifest containing file size, SHA-256, UTC creation time, and the service alias. Protect backup files and manifests with the same access controls as the database.

`restore_backup` verifies the sidecar checksum and restores with `--exit-on-error --single-transaction` into a pre-created empty database. It never drops or cleans objects. Restore into a disposable database and verify application-level consistency before any production recovery. A restore should be treated as an operator-approved action.

`plan_retention` is dry-run only: it returns expired archives older than the configured retention period while preserving at least `keep_latest` archives. It never deletes files. Review the plan and verify a recent backup and restore drill before implementing any deletion automation. A separate follow-up must include sidecar cleanup, legal holds, off-site copies, encryption-at-rest, and alerting.

No actual database backup, restore, or delete was run during development because PostgreSQL tools and a database service are not configured locally. Unit tests mock process calls and operate only in temporary directories.
