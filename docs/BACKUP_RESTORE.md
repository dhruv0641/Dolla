# Encrypted PostgreSQL backup, restore and retention

## Requirements and key custody

The maintenance module requires compatible `pg_dump`, `pg_restore`, and `age` executables on `PATH`. PostgreSQL credentials come through a protected libpq service file (`PGSERVICEFILE`) and its password file, never command-line arguments. Backups require a native age public recipient; restores require a private age identity file supplied by a secret manager or a protected operator mount. The private key content is never read by application code, written to manifests, or placed in process arguments. Use a restrictive file ACL and keep a separately protected recovery copy; losing every matching identity makes the encrypted archives unrecoverable.

The backup pipeline streams `pg_dump` custom-format output directly into `age` and writes only ciphertext to the archive directory. It does not create an intermediate plaintext dump file. The final artifact is named `flowx-<UTC timestamp>.dump.age`; a sidecar JSON manifest records ciphertext size, SHA-256, creation time, service alias and `encryption: age`. Protect both files and the archive directory with database-equivalent access controls. The checksum detects accidental corruption; decryption authenticates the age ciphertext. Age recipient encryption does not authenticate who created an archive, and the unsigned manifest may be replaced along with it. Restrict archive write access and use separately controlled provenance or signed manifests where origin verification is required. The manifest may reveal the service alias. Child processes receive only the OS launch variables and the database tools receive the configured `PGSERVICE` and `PGSERVICEFILE`; unrelated inherited environment values are not forwarded. Tool execution has a configurable per-process timeout (one hour by default); set it to match expected database size and recovery time.

## Backup runbook

1. Confirm the intended libpq service alias, protected service file, backup destination permissions, age recipient and remaining storage.
2. Run `create_backup(directory, service_name, service_file, recipient)`. The function refuses duplicate timestamps, uses a same-directory temporary ciphertext file, verifies that encryption produced non-empty output, hashes the encrypted artifact, and atomically publishes the archive and manifest.
3. Confirm that both `.dump.age` and `.manifest.json` exist, the archive is non-empty, and only ciphertext is in the destination. Transfer/copy both files to the approved off-site store using its access and retention controls.
4. Record the recovery identity reference and custody location in the operator's approved secrets system, not in the manifest, repository, ticket, or chat.

Recipient rotation applies to newly created backups. Keep the old identity available until all archives encrypted only to its recipient have expired or have been explicitly re-encrypted through a separately reviewed process. Do not delete old keys based only on creation of a new backup.

## Restore runbook

1. Obtain a matching identity through the secret manager and mount it at a protected path. Select a pre-created empty disposable target database and a protected libpq service alias.
2. Call `restore_backup(archive_path, target_service, service_file, identity_file)`. The function copies the ciphertext to a private temporary snapshot while verifying its sidecar name, encryption marker, size and checksum. It fully decrypts the snapshot once to a discard sink, so the age authentication tag is checked before the database can change. It then decrypts the same snapshot into `pg_restore --exit-on-error --single-transaction`. Only encrypted bytes are written to disk. Keep the target empty and disposable; transactional rollback is attempted on restore errors.
3. Verify schema/data consistency and application-level invariants in the disposable database. Confirm readiness and critical queries before considering any recovery cutover.
4. Treat production recovery as a separately approved operator action. This function never drops or cleans objects and is not a production cutover tool.

If restore fails, preserve the original encrypted archive and manifest, inspect the target database, verify the identity and service alias, and retry only against a clean disposable database. Do not place a decrypted dump in a shared temp directory or log tool output containing database details.

## Retention and operational limits

`plan_retention` is dry-run only. It selects expired `.dump.age` archives older than the configured period while preserving at least `keep_latest`; it never deletes files or sidecars. Review each plan, apply approved deletion through the storage operator's process, and account for legal holds and off-site copies. Legacy plaintext `.dump` files are intentionally excluded from the encrypted retention plan; inventory and securely migrate/delete them under an explicit operator procedure.

No real database backup, restore, key generation, or deletion was run during development because PostgreSQL tools, age, a database service and recovery identities are not configured. Unit tests mock pipeline processes and operate only in temporary directories. Schedule, off-site replication, encryption-key escrow, restore drills, checksum/age-failure alerts and deployment integration remain operational responsibilities; this code does not claim that backups are currently running.
