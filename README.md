# Orangetheory → Garmin Connect Auto-Sync

Automatically pulls your Orangetheory workouts (including heart rate data)
and uploads them to Garmin Connect, twice a day, for free using GitHub Actions.

No paid subscriptions required. No computer needs to stay on.

⚠️ Uses an **unofficial** OTF API ([`otf-api`](https://github.com/NodeJSmith/otf-api))
and an unofficial Garmin Connect client ([`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)).
Neither is affiliated with Orangetheory or Garmin. They could break if either
company changes their backend.

---

## What you get in Garmin Connect

Each uploaded workout shows up as an activity with:
- Activity type: **Other** (indoor)
- Duration and calories
- Full heart rate graph (second-by-second), when OTF has finished processing
- Description with splat points, avg/peak HR, and zone time breakdown
- Activity name like "Orangetheory – Orange 60"

---

## Setup (one-time, ~10 minutes)

### Step 1: Install Python on your computer

You need Python 3.10 or later. Download from [python.org](https://python.org) if
you don't already have it. To check: open a terminal and type `python3 --version`.

### Step 2: Generate a Garmin session token

Garmin requires MFA when logging in from a new location (like GitHub's servers).
To get around this, you log in once on your own computer and save a reusable
session token.

1. Install the required library:
   ```
   pip install garminconnect
   ```
2. Download `get_garmin_session.py` from this project to your computer
3. Run it:
   ```
   python get_garmin_session.py
   ```
4. Enter your Garmin email and password when prompted
5. If Garmin sends you a one-time code, enter that too
6. The script prints a long token string — copy the **entire** thing

### Step 3: Create a private GitHub repo

1. Go to [github.com](https://github.com) and create a **new private repository**
   (private keeps your credentials safer, though secrets are encrypted either way)
2. Upload these files, keeping the folder structure:
   ```
   sync_otf_to_garmin.py
   requirements.txt
   .github/
     workflows/
       sync.yml
   ```
   Easiest approach: use "Add file → Upload files" in the GitHub web UI.
   For the workflow file, you may need to create the `.github/workflows/` path
   manually — type the full path `sync.yml` when prompted, and GitHub will
   create the nested folders.

   (`get_garmin_session.py` is just for the one-time setup on your computer;
   it doesn't need to go in the repo.)

### Step 4: Add secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these three secrets (exact names matter):

| Secret name | Value |
|---|---|
| `OTF_EMAIL` | Your Orangetheory account email |
| `OTF_PASSWORD` | Your Orangetheory account password |
| `GARMINTOKENS` | The long token string from Step 2 |

### Step 5: Test it

1. Go to the **Actions** tab in your GitHub repo
2. Click **"Sync OTF workouts to Garmin Connect"** in the left sidebar
3. Click **"Run workflow" → "Run workflow"** (the green button)
4. Click into the running job to watch the logs

A successful run looks like:
```
[2026-06-16T20:00:01Z] Starting OTF -> Garmin Connect sync
[2026-06-16T20:00:03Z] Found 1 OTF workout(s) since 2026-06-14
[2026-06-16T20:00:04Z] Garmin login successful.
[2026-06-16T20:00:05Z] Found 3 existing Garmin activities in the lookback window
[2026-06-16T20:00:07Z] Uploaded 'Orangetheory – Orange 60' (2026-06-15 18:30:00+00:00) -- Garmin activity id 12345678901 [with HR telemetry]
[2026-06-16T20:00:07Z] Done. Uploaded=1 Skipped=0 Failed=0
```

Then open Garmin Connect — your workout should be there!

---

## Adjusting the sync schedule

Edit `.github/workflows/sync.yml`. The `cron` times are in **UTC**. The defaults
run at 11:00 and 23:00 UTC. Use [crontab.guru](https://crontab.guru) to find
the right time for your timezone. Give yourself 1–2 hours after a typical class
ends, since OTF takes time to finalize workout data.

---

## Troubleshooting

**"[summary only, no HR graph]" in logs**
OTF hadn't finished processing the workout yet when the sync ran. The activity
still uploads, just without a heart rate graph. The next run will have full data
for future workouts. You can delete and re-run manually if you want the graph.

**Auth errors after working for weeks**
Garmin session tokens do eventually expire. Just re-run `get_garmin_session.py`
on your computer and update the `GARMINTOKENS` secret in GitHub.

**OTF login errors**
Orangetheory may have changed their API. Check for a newer version of `otf-api`
at [its GitHub page](https://github.com/NodeJSmith/otf-api) and update
`requirements.txt` to match.

**Duplicate activities**
The script compares workout start times (within a 10-minute window) to avoid
duplicates. If you end up with one anyway, just delete it manually in Garmin.
