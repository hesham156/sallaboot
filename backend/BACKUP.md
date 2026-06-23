# Off-site encrypted backups — setup & restore runbook

The app's only durable state is PostgreSQL (store tokens, every
conversation, contacts, orders, uploaded files as `bytea`, …). Railway's
managed snapshots are good, but they live on the **same provider**. This
adds an independent, encrypted copy on object storage you control.

```
  pg_dump -Fc  →  Fernet-encrypt  →  upload to R2  →  prune > retention
        (daily, leader-elected — exactly one backup per window)
```

## 1. Create the destination (Cloudflare R2)

1. Cloudflare dashboard → **R2** → *Create bucket* (e.g. `chatbot-backups`).
2. **R2 → Manage API Tokens → Create API Token** (Object Read & Write).
   Note the **Access Key ID**, **Secret Access Key**, and the **S3 endpoint**
   (`https://<account-id>.r2.cloudflarestorage.com`).

> Any S3-compatible store works (Backblaze B2, AWS S3) — only the endpoint
> URL changes.

## 2. Generate the backup encryption key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use a **dedicated** key (not the same as `ENCRYPTION_KEY`) so rotating the
field-level key never makes old backups unrestorable, and a leak of one key
doesn't compromise the other.

## 3. Set the env vars (every service: web + worker)

```
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=chatbot-backups
BACKUP_ENCRYPTION_KEY=<fernet-key-from-step-2>
# optional:
R2_PREFIX=backups
BACKUP_RETENTION_DAYS=30
BACKUP_INTERVAL_HOURS=24
```

⚠️ **Store `BACKUP_ENCRYPTION_KEY` offline too** (1Password / Bitwarden).
A lost key makes every stored backup permanently unrecoverable. The pipeline
**fails closed** — with no key set it refuses to upload rather than ship a
plaintext dump.

## 4. Verify

- `GET /env-check` (as super-admin) now includes a `BACKUP` block with
  `enabled: true`.
- `GET /admin/backups` — config + list of stored artifacts.
- `POST /admin/backups/run` — trigger one immediately; check the returned
  `key` / `size_bytes`, then confirm the object appears in the bucket.
- Logs: `backup_ok` / `backup_loop_ok` on success, `backup_failed` on error.

## 5. Restore (manual, deliberate)

Restore is a standalone CLI (`restore_backup.py`) — never invoked by the
running app, so it can't clobber the live DB by accident. Run it with the
same `R2_*` + `BACKUP_ENCRYPTION_KEY` env.

```bash
# See what's available
python restore_backup.py --list

# Download + decrypt the newest (or a specific --key) to a local file
python restore_backup.py --latest --out restore.dump

# Restore into a target DB YOU control — point at a scratch DB first, not
# prod by reflex.
pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "$TARGET_DATABASE_URL" restore.dump
```

After restoring, the encrypted secret fields (Salla tokens, provider API
keys) in `stores` are still ciphertext — the app decrypts them at load time
using `ENCRYPTION_KEY`. So the restored DB also needs the **matching
`ENCRYPTION_KEY`** that was active when the backup was taken (or that key in
`ENCRYPTION_KEYS_OLD`).

## Troubleshooting

- **`server version mismatch` / `aborting because of server version mismatch`** —
  `pg_dump` refuses when the server is a *newer* major than the client. The
  build pins `postgresql_16` (nixpacks). If Railway upgrades Postgres to a
  newer major, bump `postgresql_16` → the matching major in `nixpacks.toml`.
- **`pg_dump binary not found`** — only happens on local dev (the container
  ships it). Install the Postgres client tools locally to test end-to-end.
- **Backup `enabled: false`** in `/env-check` — one of the `R2_*` vars is
  missing/empty, or `DATABASE_URL` is unset.

## 6. Test the restore periodically

A backup you've never restored is a hope, not a backup. Quarterly: restore
the latest artifact into a throwaway Postgres, point a local app instance at
it with the matching `ENCRYPTION_KEY`, and confirm stores + conversations
load. Document the date you last did this.
