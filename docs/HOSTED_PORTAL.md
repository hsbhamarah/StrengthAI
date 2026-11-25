# Hosted client portal

This is a separate runtime from the Windows-only coach app. The local app remains at `strengthos.main:app`; the hosted entry point is `strengthos.hosted:app`. Use the local app for existing encrypted data and approved workbook imports until migration is reviewed. The hosted portal adds coach-authored templates, published assignments, invited clients, actuals, and recovery.

## Local synthetic preview

Run `run-local.ps1` to build the UI, migrate the ignored preview database, and open the portal on loopback. The local preview opens directly as coach without a code. Existing coach credentials from the older workbook workspace are separate. For a manual start, use:

```powershell
$env:STRENGTHOS_DATABASE_URL = 'sqlite:///data/portal_preview.db'
$env:STRENGTHOS_PUBLIC_ORIGIN = 'http://127.0.0.1:8001'
$env:STRENGTHOS_LOCAL_NO_AUTH = '1'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn strengthos.hosted:app --host 127.0.0.1 --port 8001
```

Run `npm run build` before starting the server. The browser opens at `http://127.0.0.1:8001/portal`. Use **Create weekly plan** to build a week, publish it, choose a client and start date, and assign it. Use **Copy as next week** to make an editable new draft; publishing and assigning it preserves the prior week and its actuals. Local access requires an explicit flag, a loopback origin and client address, and a SQLite preview database; the public deployment never enables it. This HTTP exception is accepted only for a loopback preview containing synthetic data. Invite links cannot be used from a client's device until the portal is deployed publicly with HTTPS.

## India-hosted deployment

Choose OCI **India West (Mumbai), `ap-mumbai-1`, as the home region** when creating the account; Always Free compute is confined to that home region. Confirm the VM, boot volume, and Object Storage bucket are all in Mumbai and tagged Always Free before provisioning. If free capacity is unavailable, keep testing locally and wait. Do not create paid resources. Free instances can be reclaimed when idle, so backups are required before real use.

1. On an Always Free Ubuntu Arm VM, install Python 3.12, PostgreSQL, Node.js, Caddy, OCI CLI, and security updates from official packages. Create an unprivileged `strengthos` Unix user. Put source under `/opt/strengthos`, create `/var/lib/strengthos`, and create a Python virtual environment with `requirements-hosted.txt`. Build the Vite UI with `npm run build`.
2. Create a PostgreSQL role and database named `strengthos` (for example, as `postgres`: `createuser --login strengthos` and `createdb --owner=strengthos strengthos`). Use Unix-socket peer authentication for the `strengthos` service user. Set `/etc/strengthos/hosted.env` (root-owned, mode `0600`) to `STRENGTHOS_DATABASE_URL=postgresql+psycopg://strengthos@/strengthos?host=/var/run/postgresql`, `STRENGTHOS_PUBLIC_ORIGIN=https://YOUR-HOST.duckdns.org`, `STRENGTHOS_OBJECT_NAMESPACE=...`, and `STRENGTHOS_BACKUP_BUCKET=...`.
3. Replace `YOUR-HOST.duckdns.org` in `deploy/Caddyfile` with the actual hostname. Run `alembic upgrade head` with the environment file loaded. Run `python -m strengthos.hosted` as the `strengthos` service user to create the single coach account and enroll an authenticator. Install `deploy/strengthos.service` and `deploy/Caddyfile`, then start both services. Caddy obtains and renews HTTPS certificates. Open only ports 80 and 443 to the public; restrict SSH to the coach's IP and key. PostgreSQL and Uvicorn remain bound locally.
4. Create a private Object Storage bucket in Mumbai. Grant the VM instance principal write access only to that bucket. Install the backup service and timer in `deploy/`, and set a seven-day bucket lifecycle deletion rule within the Always Free quota. Backups are encrypted at rest by OCI; keep the bucket private. Check timer failures and bucket growth. Download one backup to a protected temporary path, create `strengthos_restore_check` owned by `strengthos`, run `pg_restore --dbname=strengthos_restore_check --no-owner --no-privileges BACKUP.dump` as that user, and compare table counts before inviting clients. Remove the temporary database and file after verification.
5. Apply OS and dependency security updates, review audit entries, and repeat restore checks regularly. Keep athlete details, recovery narratives, tokens, workbook contents, and database dumps out of logs and Git. No third-party analytics are loaded by the portal.

No cloud resources or public DNS records are created by this repository. A real domain, OCI account, bucket, and validated restore are release gates.

## Reviewed transfer from the Windows workspace

With the local encrypted workspace available, run `python -m strengthos.transfer export PATH` and enter a passphrase of at least 16 characters. The export includes canonical athletes, prescriptions, actuals, approved source lineage, and prior source revisions. It excludes credentials, raw workbook binaries, preview payloads, and external source IDs. Review the printed table counts and keep the encrypted `.strengthtransfer` file outside Git.

On a fresh hosted database that already has its coach account, run `python -m strengthos.transfer import PATH`. It shows counts without writing anything. Type `IMPORT` only after reviewing those counts and the destination. The command refuses to import into a database that already has athletes. Verify the portal counts, metric samples, and a backup restore before retiring local data or Google Sheets.

## Security and operation limits

- Public coach registration is command-line only; the loopback preview permits one-time coach enrollment in the UI. Client invitations expire after 72 hours and can be revoked or reissued; reissuing revokes old sessions. The coach uses password plus TOTP or a one-time recovery code. Clients use passwords of at least 12 characters. Account deactivation revokes sessions.
- Sessions are stored server-side, expire after eight hours or one hour idle, and use secure same-origin cookies in production. Writes require a CSRF token and matching Origin. Login attempts are limited in the single worker. The app must remain one worker until throttling moves to a shared store.
- Client queries are filtered by their athlete ID at the database boundary. The coach can inspect set and recovery revision history. A client can correct only their own prescribed sets and weeks. Missing, failed, skipped, and completed actuals remain distinct.
- Workbook uploads are coach-only, capped at 10 MB and 100 MB archive expansion, parsed as inert `.xlsx` data, and dropped after draft approval or 24 hours. Preview and snapshot hashes must match before approval. Imported actuals do not enter a new program draft.
- Public HTTPS, region placement, backup restoration, mobile usability, and security checks must pass before real clients are invited. The free VM is a single point of failure; do not claim an uptime or performance target without measurement.
