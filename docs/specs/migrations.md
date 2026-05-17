# Schema Migrations — Runner, Ordering, Backups, Rollback

> Companion spec to `docs/RETRODB_DESIGN_STANDARDS.md §25`. §25 owns the
> **authoring rules** (the `apply(conn)` signature, idempotency idioms,
> append-only invariant, transaction ownership, test placement). This doc owns
> everything *around* the author's keyboard: how the runner boots, why the
> numbering rules exist, what happens on failure, how backups interact with the
> upgrade path, and what "rollback" does and doesn't mean for RetroDB.

---

## 1. Purpose

RetroDB ships with a tiny, dependency-free schema migration system in
`services/migrations/`. Each migration is a single `apply(conn)` function in
`services/migrations/scripts/NNN_short_name.py`. A boot-time runner
(`services/database_init.init_database`) walks every migration whose number
exceeds the database's stored `PRAGMA user_version`, runs them in order inside
their own transactions, and bumps `user_version` to match. There is no Alembic,
no DSL, no metadata table — the migration list is just a Python list in
`services/migrations/__init__.py:MIGRATIONS` and the version cursor is just an
integer SQLite stores in the database header.

§25 covers **how to author one of these files**. This document covers **how the
runner uses them**, why the surrounding rules exist (numbering, append-only,
backups, rollback), and what the contract is for any future migration.

---

## 2. Scope of this document

| In scope (this doc) | Out of scope (covered by §25) |
| --- | --- |
| Runner lifecycle and boot ordering | The `apply(conn)` signature |
| `PRAGMA user_version` semantics | `CREATE … IF NOT EXISTS` and other idempotency idioms |
| Numbering / file-naming contract | `try/except sqlite3.OperationalError` for `ADD COLUMN` |
| Transaction policy (`BEGIN IMMEDIATE`, `busy_timeout`) | Where to place the unit test for a new migration |
| Backup behaviour and backup retention | What "append-only" means at the source-edit level |
| Rollback story (backup-restore vs `user_version` rewind) | |
| Cascade-FK pattern for table rebuilds | |
| Walk-through of the 12 currently-landed migrations | |

Read §25 first for the authoring rules. Come back here when you need to know
*what the runner does to your file at boot* or *what guarantees the system
makes when something goes wrong*.

---

## 3. `PRAGMA user_version` — the version cursor

SQLite reserves a 32-bit integer in the database header called `user_version`,
zero by default, mutable via `PRAGMA user_version = N`. RetroDB co-opts it as
the "highest migration number applied to this database" cursor:

- A fresh database opens at `user_version = 0`.
- Migration N (1-indexed position in `MIGRATIONS`) runs only when
  `user_version < N`.
- After a successful migration N, the runner sets `user_version = N` inside the
  same transaction as the DDL.
- If the DB's `user_version` is *higher* than `latest_version()` (i.e. someone
  downgraded the app), the runner raises rather than try to "fix" it.

This is the whole tracking mechanism. There is no `schema_migrations` table, no
checksum, no name-vs-number cross-check. The trade-off: zero dependencies, zero
metadata to keep in sync, but **the numbering convention IS the contract** — if
two developers both grab number 013 on parallel branches, the merge breaks.
(Mitigation: §25 calls for the next-number probe before opening a PR; reviewers
are the second line of defence.)

Pass 20 (`roadmap.md`) is the bake-in commit for this system: prior to v2.91 the
database carried a half-dozen ad-hoc `_migrate_*` helpers that re-ran every
startup. Pass 20 collapsed them into numbered migrations and added the
`user_version`-driven runner.

---

## 4. Numbering and append-only

Filename format: `NNN_short_snake_case.py`, where `NNN` is zero-padded and
matches the file's 1-indexed position in
`services/migrations/__init__.py:MIGRATIONS`. The list is the source of truth;
the filename prefix is documentation. The two must agree (and the test
`tests/test_migrations.py::TestVersionHelpers::test_latest_matches_migrations_length`
pins it).

**Rules — extending §25.3:**

1. **Append only.** Add a new entry at the end of `MIGRATIONS`. Never insert,
   reorder, or delete.
2. **Never edit a landed migration's body.** Production databases have already
   advanced past it; your edit will run on no DB that hasn't *already* run the
   old version. Schema typos and bugs are corrected by adding a *new* migration
   that adjusts what the buggy one left behind.
3. **No re-numbering, ever.** Once shipped in a tagged release, `012_emulators`
   is forever migration number 12. Renaming to `013_emulators` would (a) leave
   every production DB pointing at a `user_version` that no longer maps to any
   migration, and (b) on next boot, re-run the migration as "13" — possibly
   against a schema that already carries the changes, possibly raising a
   non-idempotent error.

**Why this matters in practice.** Roadmap Pass 41.2 is a cautionary tale: the
original migrations 007/008/009 used `PRAGMA foreign_keys = OFF` inside the
runner's transaction. SQLite silently ignores FK-state changes mid-transaction,
so the PRAGMA was a no-op. The fix wasn't to edit 007–009; it was to switch
them to `PRAGMA defer_foreign_keys = ON` (which *does* work in a txn) **as a
new migration policy applied to all future rebuilds**, plus a runner-level
change. The author edits never went back into landed files because production
DBs had already executed them — there was no "second chance" to slip a fix in.

---

## 5. Runner lifecycle

Boot path (from `app.py`):

```
ensure_user_tables()   →  init_database()   →  Flask starts
                              │
                              ├─ open sqlite3.connect(config.DB_PATH)
                              ├─ chmod 0o600  (Pass 35.1)
                              ├─ PRAGMA foreign_keys = ON
                              ├─ PRAGMA journal_mode = WAL
                              ├─ PRAGMA journal_size_limit = 67108864
                              ├─ PRAGMA busy_timeout = 5000   (Pass 45.10)
                              ├─ migrations.apply_pending(conn)
                              │      ↓
                              │   for N in pending_versions:
                              │     BEGIN IMMEDIATE
                              │     module.apply(conn)
                              │     PRAGMA user_version = N
                              │     COMMIT     (or ROLLBACK on error)
                              │     log "Applied NNN_…"
                              ├─ PRAGMA optimize
                              └─ close()
```

Why `ensure_user_tables` runs *first*: migrations 005–010 backfill legacy
single-tenant rows to the first admin's `user_id`. If the `users` table doesn't
exist yet at migration time, the backfill is a no-op — fine for a truly fresh
install, but a footgun on upgrades. `ensure_user_tables` creates the table and
seeds the default admin before migrations run, so backfill always has a target.

**Failure handling.** If any migration raises, the runner calls `ROLLBACK`,
logs an exception with the migration name, and re-raises. The DB stays at the
previous `user_version`. Flask startup aborts because `init_database` raised
into `app.py`. Operationally:

- The DB is consistent — either fully at version N-1 or fully at version N,
  never half-applied.
- The app does not start. Systemd / the supervisor restarts it; on the next
  boot the same migration retries.
- This is intentional: a half-migrated DB serving requests is far worse than
  downtime.

There is **no skip-on-failure** path. If a migration is broken, it stays
broken until the author ships a fix (which, per §4, is a *new* migration that
patches what the broken one half-did). The "stuck DB" failure mode is loud and
fixable; the alternative — silent partial progress — would be catastrophic.

---

## 6. Transactions — `BEGIN IMMEDIATE` + `busy_timeout`

Each migration runs inside a single transaction the runner owns. The author's
`apply(conn)` must not call `conn.commit()` or `conn.rollback()` — that's the
runner's job. The migration's DDL/data changes and the matching
`PRAGMA user_version = N` are inside the same transaction, so a crash mid-DDL
cannot leave the database with the new schema but the old version (or vice
versa).

**Lock acquisition mode (Pass 45.10):**

- The runner uses `BEGIN IMMEDIATE`, not plain `BEGIN` (= `BEGIN DEFERRED`).
- Deferred acquires the write lock lazily on the first write; under WAL with a
  long-running reader, table-rebuild migrations (007/008/009) could deadlock —
  the reader holds a blocking shared lock that the deferred writer can't
  upgrade past, and SQLite's default `busy_timeout = 0` fails fast.
- `IMMEDIATE` acquires the write lock up front; combined with
  `PRAGMA busy_timeout = 5000` on the connection, it waits politely for up to
  five seconds for any concurrent reader to finish.

**Why migrations MUST run inside a transaction.** Partial-state hazards SQLite
*alone* cannot prevent:

- `ALTER TABLE` succeeds but `UPDATE` backfill raises → column exists but is
  empty.
- Table-rebuild step 6 (`INSERT INTO new SELECT FROM old`) fails halfway → the
  new table has half the rows.

Single-transaction wrapping turns every one of these into "all or nothing."
The author writes the `apply` body as if it were one atomic step, because at
the durability layer it *is*.

---

## 7. Backups

RetroDB does **not** auto-snapshot the database on every boot. Backups are
admin-triggered via `/api/backup` (and automatic before every restore via
`/api/restore/<filename>`), implemented in `routes/settings.py:api_backup` and
`services/database.py:backup_database`. The migration runner runs against the
live DB; there is no "snapshot before migrating" step.

**This is a deliberate choice, not an oversight.** Reasons:

- Backups are not free. With multi-GB databases on slow disks, snapshotting
  every boot would dominate startup latency.
- Migrations are themselves transactional (§6) — a failed migration rolls back
  cleanly. The crash window is narrow.
- The recovery story for "migration ran but broke the app" is to restore the
  newest pre-bump backup (admins are encouraged to take one immediately before
  upgrading), not to undo a single migration in place.

**Admin-triggered backup behaviour (Pass 35 + Pass 45.5):**

- Path: `<DB dir>/backups/roms_backup_YYYYMMDD_HHMMSS.db`.
- Method: SQLite **online backup API** (`src.backup(dst)`), not
  `shutil.copy2` — coordinates with WAL and concurrent writers, never produces
  a torn file.
- Permissions: chmod `0o600` *before* the post-write integrity-check open, so
  the backup never exists at the umask default while it holds password hashes
  and OAuth tokens.
- Verification: `PRAGMA integrity_check` runs against the destination; failures
  delete the file and raise rather than return a corrupt backup.
- Durability: `fsync(dst_file)` + `fsync(parent_dir)` — a power loss after the
  backup completes cannot leave a directory entry pointing at empty contents.
- Rotation: `_prune_old_backups(backup_dir, keep=config.MAX_BACKUPS)` deletes
  oldest `roms_backup_*.db` files past the cap (default `MAX_BACKUPS = 30`,
  `RETRODB_MAX_BACKUPS` env override). **`pre_restore_*.db` files are never
  pruned** — they're explicit safety nets the user relied on when running a
  restore.

**Pre-restore backups.** Every `/api/restore/<filename>` call snapshots the
*current* live DB into `pre_restore_<timestamp>.db` before overwriting it.
This is the only "undo" the system offers for a bad restore.

---

## 8. Rollback — what's possible

**Possible:**

- **Restore from backup.** Stop the app, copy a `roms_backup_*.db` file over
  `config.DB_PATH`, start the app. The runner sees the older
  `user_version` and re-applies any migrations that ran between then and now
  (which must, per §25, be idempotent — re-running them on the restored DB
  must produce the same state).
- **`pre_restore_*.db` recovery** after a bad `/api/restore` call (§7).

**Not possible without manual intervention:**

- **`PRAGMA user_version` does not go backwards on its own.** There is no
  down-migration mechanism. RetroDB is single-user-installable software with no
  notion of "deploy back to v3.5.0" — the only supported way to "go back" is
  restore a backup from before the migration ran.
- **Editing a landed migration's body to "undo" it.** Forbidden (§4). The
  database has already executed the old body; editing the file affects no
  installed instance.
- **Deleting an entry from `MIGRATIONS`.** Forbidden (§4). Removing migration
  N renumbers every later migration by minus one, which means every production
  DB at `user_version > N` is now ahead of `latest_version()`, and the runner
  raises "DB is newer than the build."

If you genuinely need to undo a migration's effect on a live install, the path
is: **add a new migration** (`NNN+1_undo_xyz.py`) that reverses the change
forwards. That migration runs once per install, lands in source control, and
is bound by the same idempotency + transactional rules.

---

## 9. Cascade FKs on rebuilt tables

SQLite cannot add a `FOREIGN KEY` clause to an existing table — only the
12-step "rebuild the table around the new shape" procedure (drop, recreate
with new schema, copy rows, drop old, rename new) can introduce FKs to a
table that didn't ship with them. Migration 011 is the canonical example;
follow its shape for any future migration that needs cascade behaviour on a
pre-existing table.

**Pattern (per migration 011, Pass 45.15):**

```python
def apply(conn):
    cursor = conn.cursor()

    # 1. Idempotency: skip if the FKs are already in place.
    if not _table_exists(cursor, 'user_game_views'):
        return
    if _foreign_key_count(cursor, 'user_game_views') >= 2:
        return

    # 2. Suspend FK enforcement for the duration of the rebuild.
    #    `defer_foreign_keys` works *inside* a transaction; auto-resets
    #    at COMMIT. (Plain `PRAGMA foreign_keys = OFF` is silently
    #    ignored mid-transaction — Pass 41.2 lesson.)
    cursor.execute("PRAGMA defer_foreign_keys = ON")

    # 3. Build the replacement table with the FK clauses you want.
    cursor.execute("""
        CREATE TABLE user_game_views_new (
            user_id     INTEGER NOT NULL,
            game_id     INTEGER NOT NULL,
            last_viewed TEXT NOT NULL,
            PRIMARY KEY (user_id, game_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # 4. Copy rows, dropping orphans inline (INNER JOIN both parents).
    #    Equivalent to running ON DELETE CASCADE retroactively.
    cursor.execute("""
        INSERT INTO user_game_views_new (user_id, game_id, last_viewed)
        SELECT v.user_id, v.game_id, v.last_viewed
          FROM user_game_views v
          INNER JOIN games g ON g.id = v.game_id
          INNER JOIN users u ON u.id = v.user_id
    """)

    # 5. Swap.
    cursor.execute("DROP TABLE user_game_views")
    cursor.execute("ALTER TABLE user_game_views_new RENAME TO user_game_views")
    cursor.execute(
        "CREATE INDEX idx_user_game_views_user_lastviewed "
        "ON user_game_views(user_id, last_viewed DESC)"
    )

    # 6. Scoped FK check — fail loudly if rebuild left dangling refs.
    #    Scoped, not unscoped, so pre-existing FK debt elsewhere in the
    #    DB doesn't block the upgrade path on legacy installs.
    violations = cursor.execute(
        "PRAGMA foreign_key_check(user_game_views)"
    ).fetchall()
    if violations:
        raise RuntimeError(f"FK violations: {violations}")
```

Notes:
- Use `PRAGMA defer_foreign_keys = ON`, **not** `PRAGMA foreign_keys = OFF`
  (the latter is a no-op inside a transaction — Pass 41.2).
- Always end with a scoped `PRAGMA foreign_key_check(<table>)` — the unscoped
  form catches every FK in the DB, which is too aggressive on legacy installs
  that may have unrelated dangling refs.
- The orphan-pruning INNER JOIN doubles as a "retroactive CASCADE." Document
  it in the migration header so reviewers understand the row-count delta.

---

## 10. Worked example — migration 012 (multi-emulator launch)

Migration 012 is the most recent and most representative migration: it adds
new tables, indexes, and additive override columns on an existing table, with
FK relationships from day one. Use it as a reference for any "new feature
needs new tables + ties into existing data" migration.

What it does:

1. `CREATE TABLE IF NOT EXISTS emulators (...)` — new registry table.
2. `CREATE TABLE IF NOT EXISTS system_emulators (...)` — many-to-many join with
   `system_id REFERENCES systems(id) ON DELETE CASCADE` and
   `emulator_id REFERENCES emulators(id) ON DELETE CASCADE`. FK clauses are
   safe here because both tables are *brand new* in this migration — no
   table-rebuild needed.
3. `_add_column_if_missing(c, 'games', 'emulator_override_id', 'INTEGER REFERENCES emulators(id)')`
   and `'launch_args_override', 'TEXT'` — additive columns on the existing
   `games` table.
4. `CREATE INDEX IF NOT EXISTS …` on `system_emulators(system_id)` and
   `(system_id, is_default)`.

Things to copy when authoring a similar migration:
- **Seed data does not go here.** Migration 012 only creates schema; seed rows
  load from `data/emulator_seeds.json` at Flask startup (`app.py`). Migrations
  ship to every install — bundling seed data into the migration would force the
  same vendor list on every user forever. Author seed-loading as a separate,
  config-driven boot-time step.
- **`CREATE TABLE IF NOT EXISTS` is idempotent**; `ALTER TABLE ADD COLUMN` is
  not (re-running raises `duplicate column name`). Use the local
  `_add_column_if_missing` helper (defined inline in 012, or import from
  `services.migrations._helpers` in newer migrations).
- **FK clauses on brand-new tables are free.** You only need the table-rebuild
  procedure (§9) when adding FKs to a table that already exists in production.

Reference: roadmap Pass 44.

---

## 11. Authoring checklist — extending §25

§25.1 gives you the file/function shape. The runtime contract this doc adds:

1. **Pick the next number** by counting entries in `MIGRATIONS` in
   `services/migrations/__init__.py` and adding one. Don't trust your local
   filesystem listing — a teammate may have a parallel branch with the same
   next number. The PR review is the merge-conflict trap.
2. **Filename** matches `NNN_short_snake_case.py`. Zero-padded.
3. **Import helpers**, don't duplicate them:
   ```python
   from services.migrations._helpers import (
       _add_column_if_missing, _table_exists, _has_column,
       _admin_user_id, _columns_ddl,
   )
   ```
   Migration 001 keeps its own helpers because it predates `_helpers.py`; new
   migrations should always import.
4. **No `conn.commit()` / `conn.rollback()`** in your `apply()`. The runner
   owns the transaction.
5. **Idempotency check up front.** If the migration is already applied (e.g.
   FK count matches, target column already present), `return` early. This
   protects against the legacy install whose pre-versioned schema already
   carries the change (§25.2).
6. **For table rebuilds**: follow §9 exactly. `defer_foreign_keys = ON`, build
   `<table>_new`, INNER JOIN parents to drop orphans, swap with `ALTER TABLE
   RENAME`, recreate indexes, scoped `foreign_key_check` before returning.
7. **Append to `MIGRATIONS`** in `services/migrations/__init__.py` — last line
   of authoring, easy to forget.
8. **Write the test** at `tests/test_migration_<N>.py` (newer pattern) or
   extend `tests/test_migrations.py` (older multi-class pattern). See §12.
9. **Manual smoke**: open a copy of a real DB at the previous version, run
   `python -c "import sqlite3, services.migrations as m; c = sqlite3.connect('roms.db'); print(m.apply_pending(c)); c.close()"`,
   verify the version advances and no rows went missing.
10. **Cross-platform check.** SQLite is uniform across platforms; the gotcha
    is path separators and file permissions in helper code. If your migration
    reads sibling files (e.g. migration 006 ingests `data/psn_tokens.json`),
    use `os.path.join` and tolerate `OSError` on Windows.

---

## 12. Testing

The canonical fixture pattern lives in `tests/test_migrations.py`:

```python
def _open(path):
    return sqlite3.connect(path)

def test_fresh_db_runs_all_migrations(tmp_path):
    path = str(tmp_path / 'fresh.db')
    conn = _open(path)
    assert migrations.current_version(conn) == 0

    applied = migrations.apply_pending(conn)
    assert applied == list(range(1, migrations.latest_version() + 1))
    assert migrations.current_version(conn) == migrations.latest_version()
```

For per-migration regression tests (`tests/test_migration_<N>.py`,
`tests/test_pass31_migrations.py`):

- **Fresh-DB happy path**: open `:memory:` or `tmp_path` DB, run
  `apply_pending`, assert new tables/columns/indexes exist.
- **Legacy install path**: hand-build the pre-migration schema (see
  `_seed_legacy` in `test_migrations.py`), insert representative rows, run
  `apply_pending`, assert the data transformation ran.
- **Idempotency**: run `apply_pending` twice, or force `PRAGMA user_version = 0`
  after the first pass and re-run. The second pass must not raise.
- **Backfill correctness**: for migrations 005–010, hand-seed a `users` table
  with a known admin id, then verify legacy rows came out owned by that admin.

The test runner also pins five whole-system invariants in
`tests/test_migrations.py`:

- Fresh DB advances 0 → `latest_version()`.
- Legacy install (pre-seeded schema, `user_version = 0`) finishes at
  `latest_version()` without erroring on already-existing objects.
- `apply_pending` is a no-op once `user_version == latest_version()`.
- A migration that raises rolls back AND leaves `user_version` untouched.
- A DB ahead of the build refuses to run.

If you add a migration and **any** of those invariants breaks, the bug is in
your migration — not in the runner.

---

## 13. The 12 currently-landed migrations

| # | File | Purpose | Notes |
| --- | --- | --- | --- |
| 001 | `001_baseline.py` | Snapshot of the v2.91.0 schema (`systems`, `games`, `tags`, `lists`, `wishlist`, `job_queue`, …) | Idempotent; uses its own local `_add_column_if_missing` (predates `_helpers.py`). |
| 002 | `002_normalize_genres.py` | Rewrite legacy genre values to canonical hyphenated forms (`FPS` → `First-Person-Shooter`, etc.). | Pure data migration; matches `FIELD_SCHEMAS` in `scraper/scrape_ai.py`. |
| 003 | `003_normalize_pegi.py` | Promote bare PEGI numbers (`12`) to `PEGI 12`. | Pure data migration. |
| 004 | `004_games_updated_at.py` | Add `games.updated_at` + INSERT/UPDATE triggers. | Pass 21 ETag scheme keys off `MAX(updated_at)`; triggers free callers from stamping it manually. |
| 005 | `005_collections_owner_id.py` | Add `owner_id` to `tags` / `lists` / `wishlist`; backfill to first admin. | Pass 27.1 — multi-user data ownership round 1. Uses `_admin_user_id` helper. |
| 006 | `006_per_user_platform_tokens.py` | Create `user_platform_tokens`; ingest legacy `psn_tokens.json` / `xbox_tokens.json`; add `user_id` to `psn_sync_status`. | Pass 27.2. Deletes ingested files. |
| 007 | `007_psn_user_id.py` | Table-rebuild `psn_games` / `psn_trophies` to add `user_id` + composite UNIQUE keys. | Pass 31.1. First rebuild migration; uses `defer_foreign_keys = ON` (Pass 41.2 lesson). |
| 008 | `008_collector_trophies_user_id.py` | Table-rebuild `collector_trophies` with composite PK `(id, user_id)`. | Pass 31.3. Per-user Collector Rank. |
| 009 | `009_achievement_tables_user_id.py` | Add `user_id` to `game_achievement_progress`, `steam_achievements`, `xbox_achievements`. | Pass 31.2. Mix of table-rebuild (one table) + additive ALTER (two tables). |
| 010 | `010_user_game_views.py` | Create `user_game_views` (per-user recently-viewed timestamps). | Pass 41.9. `games.last_viewed` becomes vestigial — kept, no longer written. |
| 011 | `011_user_game_views_cascade_fk.py` | Rebuild `user_game_views` with `ON DELETE CASCADE` FKs. | Pass 45.15. Canonical CASCADE-FK rebuild example (§9). |
| 012 | `012_emulators.py` | Create `emulators` + `system_emulators`; add `emulator_override_id` / `launch_args_override` to `games`. | Pass 44. Canonical "new tables + additive columns" example (§10). Seed data loads separately from `data/emulator_seeds.json`. |

---

## 14. Invariants

These are the contracts every migration — landed and future — must uphold.
Violating any of them breaks the upgrade path for installed users.

1. **Every migration is idempotent.** Re-running on a DB that already carries
   the change is a no-op, not an error. (§25.2, §11 step 5.)
2. **Landed migrations are immutable.** No body edits, no renames, no
   re-numbers, no deletions from `MIGRATIONS`. Fixes are forward-only: ship a
   new migration. (§4, §25.3.)
3. **The runner aborts on any migration failure.** No partial-skip, no
   "continue past the broken one." A failed migration rolls back, the version
   cursor stays put, and Flask startup raises. (§5.)
4. **Migrations run inside a single transaction with their `user_version`
   bump.** Crash-half-way states are impossible. (§6.)
5. **Backups are admin-triggered, not boot-triggered.** Rollback = restore a
   backup from before the upgrade. There is no down-migration. (§7, §8.)
6. **`PRAGMA user_version` is the single source of truth** for "what's been
   applied." No parallel tracking table, no checksums. (§3.)
7. **The numbering convention IS the merge contract.** Two PRs both claiming
   number N is a merge conflict humans must resolve before either lands.
   (§4, §11 step 1.)
