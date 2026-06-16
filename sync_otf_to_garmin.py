#!/usr/bin/env python3
"""
Sync Orangetheory workouts to Garmin Connect.

Pulls recent OTF workouts (with second-by-second heart rate telemetry where
available), converts each one into a TCX file, and uploads it to Garmin Connect
using the import endpoint — so Garmin treats them as imported activities and
does NOT re-export them to other services.

Designed to run on a schedule (e.g. GitHub Actions, daily) without any
persistent state file -- it checks Garmin's activity list each run to avoid
creating duplicates.

Required environment variables:
    OTF_EMAIL              - Orangetheory account email
    OTF_PASSWORD           - Orangetheory account password
    GARMINTOKENS           - Session token string (from get_garmin_session.py).
                             Recommended: avoids Garmin MFA prompts in CI.

Optional fallback (only if GARMINTOKENS is absent AND Garmin doesn't require MFA):
    GARMIN_EMAIL           - Garmin Connect account email
    GARMIN_PASSWORD        - Garmin Connect account password

Optional:
    LOOKBACK_HOURS         - how far back to check for OTF workouts (default 48)
"""

import os
import sys
import time
import tempfile
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from otf_api import Otf, OtfUser
from garminconnect import Garmin, GarminConnectConnectionError

LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "48"))


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Garmin auth
# ---------------------------------------------------------------------------

def garmin_login():
    """Login to Garmin Connect, preferring saved session tokens to avoid MFA."""
    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    token_str = os.environ.get("GARMINTOKENS", "")

    client = Garmin(email, password)

    if token_str:
        log("Logging into Garmin Connect using saved session tokens...")
        client.login(tokenstore=token_str)
    else:
        log("Logging into Garmin Connect using email/password (may require MFA)...")
        mfa_status, _ = client.login()
        if mfa_status:
            log(
                "ERROR: Garmin requires an MFA code, which can't be provided in CI. "
                "Run get_garmin_session.py on your own computer to generate a "
                "GARMINTOKENS secret. See README for instructions."
            )
            sys.exit(1)

    log("Garmin login successful.")
    return client


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def get_recent_garmin_start_times(garmin, since_date_str):
    """Return list of UTC datetimes for Garmin activities since given date."""
    try:
        activities = garmin.get_activities_by_date(since_date_str)
    except Exception as e:
        log(f"Warning: could not fetch Garmin activity list: {e}")
        return []

    starts = []
    for act in activities:
        raw = act.get("startTimeGMT") or act.get("startTimeLocal") or ""
        if raw:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                starts.append(dt)
            except ValueError:
                pass
    return starts


def already_uploaded(workout_start_utc, existing_starts, tolerance_minutes=10):
    for s in existing_starts:
        if abs((s - workout_start_utc).total_seconds()) <= tolerance_minutes * 60:
            return True
    return False


# ---------------------------------------------------------------------------
# TCX building
# ---------------------------------------------------------------------------

def build_tcx(workout):
    """Build a TCX document from an otf_api Workout object."""
    otf_class = workout.otf_class
    start_local = otf_class.starts_at_local
    duration_seconds = workout.active_time_seconds or 3600
    calories = workout.calories_burned or 0

    if start_local.tzinfo:
        start_utc = start_local.astimezone(timezone.utc)
    else:
        start_utc = start_local.replace(tzinfo=timezone.utc)
    start_str = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    points_xml = []
    if workout.telemetry and workout.telemetry.telemetry:
        for point in workout.telemetry.telemetry:
            if point.timestamp is None:
                continue
            ts = point.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            hr_xml = ""
            if point.hr:
                hr_xml = f"<HeartRateBpm><Value>{int(point.hr)}</Value></HeartRateBpm>"
            cal_xml = (
                f"<Calories>{int(point.agg_calories)}</Calories>"
                if point.agg_calories is not None else ""
            )
            points_xml.append(
                f"<Trackpoint><Time>{ts_str}</Time>{cal_xml}{hr_xml}</Trackpoint>"
            )

    track_xml = f"<Track>{''.join(points_xml)}</Track>" if points_xml else ""

    notes_bits = [f"Orangetheory: {escape(otf_class.name)}"]
    if workout.coach:
        notes_bits.append(f"Coach: {escape(workout.coach)}")
    if workout.splat_points is not None:
        notes_bits.append(f"Splat points: {workout.splat_points}")
    if workout.heart_rate:
        notes_bits.append(
            f"Avg HR: {workout.heart_rate.avg_hr} | Peak HR: {workout.heart_rate.peak_hr}"
        )
    if workout.zone_time_minutes:
        z = workout.zone_time_minutes
        notes_bits.append(
            f"Zones (min) Gray/Blue/Green/Orange/Red: "
            f"{z.gray}/{z.blue}/{z.green}/{z.orange}/{z.red}"
        )
    notes = " | ".join(notes_bits)

    tcx = f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Other">
      <Id>{start_str}</Id>
      <Lap StartTime="{start_str}">
        <TotalTimeSeconds>{duration_seconds}</TotalTimeSeconds>
        <DistanceMeters>0</DistanceMeters>
        <Calories>{calories}</Calories>
        <Intensity>Active</Intensity>
        <TriggerMethod>Manual</TriggerMethod>
        {track_xml}
        <Notes>{notes}</Notes>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>"""
    return tcx.encode("utf-8"), start_utc, notes


def workout_display_name(workout):
    cls = workout.otf_class.name if workout.otf_class else "Class"
    return f"Orangetheory – {cls}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("Starting OTF -> Garmin Connect sync")

    missing_otf = [v for v in ("OTF_EMAIL", "OTF_PASSWORD") if v not in os.environ]
    if missing_otf:
        log(f"ERROR: missing required environment variables: {missing_otf}")
        sys.exit(1)
    if "GARMINTOKENS" not in os.environ and (
        "GARMIN_EMAIL" not in os.environ or "GARMIN_PASSWORD" not in os.environ
    ):
        log("ERROR: must set either GARMINTOKENS or both GARMIN_EMAIL + GARMIN_PASSWORD")
        sys.exit(1)

    # --- Connect to OTF ---
    otf = Otf(user=OtfUser(os.environ["OTF_EMAIL"], os.environ["OTF_PASSWORD"]))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    since_date_str = cutoff.strftime("%Y-%m-%d")
    workouts = otf.workouts.get_workouts(start_date=since_date_str)
    log(f"Found {len(workouts)} OTF workout(s) since {since_date_str}")

    if not workouts:
        log("Nothing to sync. Done.")
        return

    # --- Connect to Garmin ---
    garmin = garmin_login()
    existing_starts = get_recent_garmin_start_times(garmin, since_date_str)
    log(f"Found {len(existing_starts)} existing Garmin activities in the lookback window")

    uploaded, skipped, failed = 0, 0, 0

    for workout in workouts:
        otf_class = workout.otf_class
        start_local = otf_class.starts_at_local
        start_utc = (
            start_local.astimezone(timezone.utc)
            if start_local.tzinfo
            else start_local.replace(tzinfo=timezone.utc)
        )

        if already_uploaded(start_utc, existing_starts):
            log(f"Skipping '{otf_class.name}' at {start_utc} -- already in Garmin")
            skipped += 1
            continue

        try:
            tcx_bytes, _, notes = build_tcx(workout)
            has_telemetry = bool(workout.telemetry and workout.telemetry.telemetry)

            # garminconnect.import_activity() takes a file path, so write to a temp file
            with tempfile.NamedTemporaryFile(suffix=".tcx", delete=False) as tmp:
                tmp.write(tcx_bytes)
                tmp_path = tmp.name

            try:
                result = garmin.import_activity(tmp_path)
                successes = result.get("detailedImportResult", {}).get("successes", [])
                failures = result.get("detailedImportResult", {}).get("failures", [])

                if successes:
                    internal_id = successes[0].get("internalId", "?")
                    telemetry_note = "[with HR telemetry]" if has_telemetry else "[summary only, no HR graph]"
                    log(f"Uploaded '{workout_display_name(workout)}' ({start_utc}) "
                        f"-- Garmin activity id {internal_id} {telemetry_note}")
                    # Rename the activity to something friendly
                    try:
                        garmin.set_activity_name(internal_id, workout_display_name(workout))
                    except Exception:
                        pass  # naming is nice-to-have
                elif failures:
                    log(f"Garmin reported upload failure for '{otf_class.name}': {failures}")
                    failed += 1
                    continue
                else:
                    log(f"Uploaded '{workout_display_name(workout)}' ({start_utc})")

            except GarminConnectConnectionError as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    log(f"Garmin reports duplicate for '{otf_class.name}', skipping.")
                    skipped += 1
                    continue
                raise
            finally:
                os.unlink(tmp_path)

            uploaded += 1
            time.sleep(2)  # be polite to Garmin's servers

        except Exception as e:
            log(f"FAILED to process '{otf_class.name}' at {start_utc}: {e}")
            failed += 1

    log(f"Done. Uploaded={uploaded} Skipped={skipped} Failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
