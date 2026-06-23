# Deploy notes — Phase 1F

This file is the operator-facing summary of what changed in Phase 1F and
how to deploy it. Keep it short; details live in the code and in
`backend/alembic/` migrations.

## What changed

1. **Schema migrations now go through Alembic.** The legacy
   `database._create_tables()` block is still idempotent and runs on
   startup as a safety net, but every future schema change should land
   as a new file in `backend/alembic/versions/`.
2. **A separate `worker.py` process can drain inbox/outbox and run
   periodic loops.** The web process can still run both (default), but a
   dedicated worker is recommended once you scale past one instance.
3. **Periodic loops are leader-elected.** Running them on every instance
   is safe — only one wins the DB row lease per iteration.
4. **Code is split into routers/** (Phase 2a). `main.py` shrank from
   4,365 lines to ~2,850. Module layout:
    - `models.py` — Pydantic request/response schemas
    - `middleware.py` — auth + CORS middlewares
    - `lifecycle.py` — startup / shutdown / drainers / periodic loops
    - `crypto.py` — Fernet encryption (already there since Phase C9)
    - `realtime.py` — Postgres LISTEN/NOTIFY pubsub
    - `routers/public.py` — landing pages, /health, /env-check, /widget.js, /snippet
    - `routers/auth.py` — login + token verify
    - `routers/webhooks.py` — Salla + WhatsApp webhooks + per-event handlers
    - `main.py` — remaining: chat endpoints, admin conversations / settings /
      employees / analytics / orders. These will move to routers/ in
      Phase 2b without changing any URL.

## Running migrations

```bash
# Local
export DATABASE_URL=postgresql://...
alembic upgrade head    # creates / patches schema to the latest migration
alembic history         # show timeline
alembic current         # which migration the DB is on

# To author a new migration:
alembic revision -m "describe change"
# Edit the generated file in alembic/versions/, then re-run upgrade head
```

`alembic upgrade head` is wired into the Railway start command (see
`railway.toml`) and into the `nixpacks.toml` and `Procfile`. Every fresh
deploy applies pending migrations atomically before the app boots.

### Migrating an existing prod DB to Alembic

The first deploy on a DB that pre-dates Alembic will fail to find the
`alembic_version` table. One-time fix from a shell with `DATABASE_URL`
exported:

```bash
alembic stamp head    # marks the current schema as up-to-date
                      # WITHOUT actually running migrations
```

Subsequent deploys work normally.

## Deploy topologies

### Topology A: single service (default — what you have now)

One Railway service, one process, runs everything:

- Web requests
- Inbox + outbox drainers (in-process)
- Periodic loops (token refresh, dirty flush, cleanup)

Zero config — works as-is. Acceptable up to ~2–3 instances behind
Railway's load balancer.

### Topology B: split web + worker (recommended for scale)

Create a SECOND Railway service from the same repo:

| Service | Start command                                              | Env vars                                  |
| ------- | ---------------------------------------------------------- | ----------------------------------------- |
| `web`   | `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT` | `ENABLE_DRAINERS=false`, `ENABLE_PERIODIC=false` |
| `worker`| `alembic upgrade head && python worker.py`                 | (none required — worker.py force-enables) |

Both services share the same `DATABASE_URL`, `ADMIN_SECRET`,
`SALLA_WEBHOOK_SECRET`, etc. Migrations run on either service whenever
it boots — `alembic upgrade head` is idempotent on an up-to-date DB.

Scale `web` for HTTP capacity, scale `worker` separately for queue
throughput (typically `worker` = 1 is enough; the drainers handle
hundreds of events/sec on Railway hobby plan).

## Env vars introduced in Phase 1F

| Var                | Default | Purpose                                                              |
| ------------------ | ------- | -------------------------------------------------------------------- |
| `ENABLE_DRAINERS`  | `true`  | If `false`, web process skips inbox/outbox drainers.                 |
| `ENABLE_PERIODIC`  | `true`  | If `false`, web process skips token refresh / flush / cleanup loops. |
| `WORKER_ROLE`      | `web`   | Stamped into `_WORKER_ID` and `leader_locks.holder` for diagnostics. |
| `INBOX_BATCH_SIZE` | `20`    | Rows claimed per drainer iteration.                                  |
| `OUTBOX_BATCH_SIZE`| `20`    | Same for outbound.                                                   |

## Env vars introduced in Phase C9 (encryption)

| Var                    | Required | Purpose                                                              |
| ---------------------- | -------- | -------------------------------------------------------------------- |
| `ENCRYPTION_KEY`       | **YES**  | Fernet key for encrypting Salla tokens + provider API keys at rest. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ENCRYPTION_KEYS_OLD`  | no       | CSV of previous keys (decrypt-only). Used during rotation to read ciphertext written with an old key while new writes use `ENCRYPTION_KEY`. Remove after the rewrite migration finishes. |

⚠️  **Losing `ENCRYPTION_KEY` is unrecoverable.** Every Salla access token,
refresh token, and provider API key in the DB becomes garbage. Store the
value in Railway env vars + an offline backup (1Password / Bitwarden).

### Key rotation procedure
1. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Set `ENCRYPTION_KEYS_OLD=<current-key>` on every Railway service.
3. Set `ENCRYPTION_KEY=<new-key>` on every Railway service.
4. Redeploy — old ciphertexts still decrypt via `ENCRYPTION_KEYS_OLD`; new writes use the new key.
5. Rewrite every existing row onto the new key: `python rotate_encryption_key.py`
   (preview first with `--dry-run`). This is **required** — `crypto.encrypt()`
   is idempotent on ciphertext, so rows are NOT re-keyed by normal saves; without
   this step the old key can never be retired.
6. Confirm a re-run reports `rotated=0 errors=0`, then remove `ENCRYPTION_KEYS_OLD`
   from every service and redeploy.

### First-deploy migration
- Migration `0002_encrypt_existing_secrets` reads every `stores` row, encrypts any plaintext field, writes it back.
- It **errors loudly** if `ENCRYPTION_KEY` is unset — deploy will halt before serving traffic. This is intentional: encrypting with an ephemeral key would render every row unreadable on the next restart.
- The migration is idempotent — re-running on an already-encrypted DB is a no-op.

## Off-site encrypted backups

Railway's managed Postgres snapshots live on the same provider — a billing
lapse, account compromise, or region incident takes the DB *and* its
snapshots together. `backup.py` adds an independent copy: a daily,
leader-elected `pg_dump -Fc` that is encrypted and uploaded to S3-compatible
object storage (Cloudflare R2 recommended). See `BACKUP.md` for the full
setup + restore runbook.

| Var                     | Required | Purpose                                                                 |
| ----------------------- | -------- | ----------------------------------------------------------------------- |
| `R2_ENDPOINT_URL`       | for backups | e.g. `https://<account>.r2.cloudflarestorage.com`                    |
| `R2_ACCESS_KEY_ID`      | for backups | R2 / S3 access key id.                                               |
| `R2_SECRET_ACCESS_KEY`  | for backups | R2 / S3 secret.                                                     |
| `R2_BUCKET`             | for backups | Existing bucket name.                                                |
| `R2_PREFIX`             | no       | Object key prefix (default `backups`).                                  |
| `BACKUP_ENCRYPTION_KEY` | strongly recommended | Dedicated Fernet key for the dump artifact (separate from `ENCRYPTION_KEY` so rotating one doesn't break the other). Falls back to `ENCRYPTION_KEY` if unset. |
| `BACKUP_RETENTION_DAYS` | no       | Delete copies older than this (default `30`).                           |
| `BACKUP_INTERVAL_HOURS` | no       | Backup cadence (default `24`).                                          |

⚠️ The pipeline **fails closed**: if neither `BACKUP_ENCRYPTION_KEY` nor
`ENCRYPTION_KEY` is set, it refuses to upload rather than ship a plaintext
DB dump. Keep an offline copy of `BACKUP_ENCRYPTION_KEY` — a lost key makes
every stored backup unrecoverable.

- Status + manual run (super-admin): `GET /admin/backups`, `POST /admin/backups/run`.
- Restore: `python restore_backup.py --latest --out restore.dump` then `pg_restore`.

## Database & network hardening

- **Use Railway's private network for `DATABASE_URL`.** Link the Postgres
  service to the app via the private (`*.railway.internal`) host, not the
  public proxy. Internal traffic never leaves Railway's network, so the DB
  isn't reachable from the public internet. Only switch to the public proxy
  temporarily for an admin task (e.g. running `rotate_encryption_key.py`
  from your laptop), then switch back.
- **Don't expose Postgres publicly by default.** If a public endpoint is
  enabled for a one-off, disable it again afterward. The encrypted secret
  fields limit blast radius, but customer PII (conversations, contacts) is
  plaintext in the DB — network isolation is the primary control for it.
- **Keep TLS on** for any non-private connection (asyncpg negotiates SSL
  with Railway's managed PG automatically; don't pin `sslmode=disable`).
- **Least-privilege object-storage tokens.** The R2 token used for backups
  needs Object Read & Write on the backup bucket only — not account-wide.
- **Rotate `BACKUP_ENCRYPTION_KEY` and `ENCRYPTION_KEY` on a schedule** (and
  immediately if a key may have leaked). See the rotation procedure above.

## Observability

- `SELECT * FROM leader_locks ORDER BY name;` — who's holding what.
- `SELECT status, COUNT(*) FROM webhook_inbox GROUP BY status;` — backlog.
- `SELECT status, COUNT(*) FROM outbox GROUP BY status;` — delivery queue.
- `SELECT status, last_error FROM webhook_inbox WHERE status='dead';` — DLQ.
- `SELECT status, kind, last_error FROM outbox WHERE status='dead';` — DLQ.

`dead` rows are kept indefinitely (never auto-pruned). Build a tiny
admin UI to inspect + replay when you can; for now treat them as
"someone needs to look at this."
