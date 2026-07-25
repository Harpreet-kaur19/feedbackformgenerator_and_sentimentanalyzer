# Making data survive on Render

The app now stores everything (forms, responses, sentiment cache) in one
SQLite file instead of loose JSON/CSV files. That fixes the *code* side
of persistence, but SQLite is still just a file — it only survives
restarts/redeploys if it lives on storage Render actually keeps around.

## You need a Persistent Disk

1. In the Render dashboard, open your web service → **Settings** → **Disks** → **Add Disk**.
2. Give it a name (e.g. `data`), a mount path (e.g. `/var/data`), and a size (1 GB is plenty to start).
3. Add an environment variable: `DATABASE_PATH=/var/data/app.db`.
4. Deploy. The app reads `DATABASE_PATH` (see `config.py`) and creates the
   database there on first boot.

**Important caveats (worth confirming against Render's current docs/pricing
page, since these terms change):**
- Persistent Disks require a paid instance type — they are not available on
  Render's free web services, so a $0 plan alone won't give you real
  persistence for either SQLite or the old JSON/CSV files.
- A disk pins the service to a **single instance** — you can't attach one
  to a horizontally-scaled (multiple-instance) service. That's fine here
  since this app was never designed to run more than one instance anyway.
- Without a disk, `DATABASE_PATH` falls back to a path inside the app's own
  ephemeral folder, which is wiped on every redeploy/restart — same
  failure mode as the old JSON files, just now in a `.db` file instead.

## Migrating your existing local data (optional, one-time)

If you already have forms/responses in the old `data/forms/*.json` and
`data/feedback/*.csv` files (from before this change), run this once,
locally, before your first SQLite deploy:

```
python migrate_legacy_data.py
```

It copies everything into `data/app.db`. Commit/upload that `app.db` (or
just re-run the same migration on Render's shell) so your existing forms
keep working after the switch.
