"""
function_app.py

Timer-triggered poller for Boomi AuditLog -> Microsoft Sentinel, via the
Logs Ingestion API. Python v2 programming model (decorator-based, no
function.json needed).

Flow (matches the design discussion):
  1. Validation      - Config() validates all required env vars up front.
  2. Reconciliation  - Log the category list + count for visibility.
  3. Build and Get   - Query Boomi (single call covers all categories via
                        OR-nested filter), following pagination.
  4. Replace fields  - Rename 'type'/'date' to schema-safe names.
  5. Ingest          - Push the full batch to Sentinel via the DCR.
  6. Debug summary   - One structured log line with counts + timing, so a
                        "silent empty interval" is always visible in
                        App Insights, not swallowed.

No checkpointing: each run queries a fixed sliding window
(now - QUERY_WINDOW_MINUTES -> now). Simple by design — see conversation
history for why we moved away from CCF's checkpoint/window model.
"""

import logging
import datetime

import azure.functions as func

from config import Config
from boomi_client import BoomiClient
from transform import transform_records
from ingest import SentinelIngestor

app = func.FunctionApp()


@app.function_name(name="BoomiAuditLogPoller")
@app.timer_trigger(
    schedule="0 */10 * * * *",   # every 10 minutes - keep in sync with QUERY_WINDOW_MINUTES
    arg_name="mytimer",
    run_on_startup=False,
    use_monitor=True,
)
def boomi_audit_log_poller(mytimer: func.TimerRequest) -> None:
    run_start = datetime.datetime.now(datetime.UTC)

    if mytimer.past_due:
        logging.warning("Timer trigger is running past due.")

    # --- Step 1: Validation ---
    try:
        config = Config()
    except ValueError:
        logging.exception("Configuration error — check Function App Application Settings.")
        raise

    # --- Step 2: Reconciliation ---
    logging.info(
        "Configured log categories (%d): %s",
        len(config.log_categories), config.log_categories,
    )

    end_time = run_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_time = (
        run_start - datetime.timedelta(minutes=config.query_window_minutes)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(
        "Polling window: %s -> %s (%d minute window)",
        start_time, end_time, config.query_window_minutes,
    )

    # --- Step 3: Build and Get ---
    client = BoomiClient(config)
    try:
        raw_records = client.fetch_all(start_time, end_time)
    except Exception:
        logging.exception("Failed to fetch records from Boomi AuditLog API — failing run.")
        raise  # fail loudly; no partial-success state to preserve

    # --- Step 4: Replace fields ---
    transformed_records = transform_records(raw_records)

    # --- Step 5: Log ingestion ---
    ingestor = SentinelIngestor(config)
    try:
        sent_count = ingestor.send(transformed_records)
    except Exception:
        logging.exception("Failed to ingest records into Sentinel — failing run.")
        raise

    # --- Step 6: Debug summary ---
    run_end = datetime.datetime.now(datetime.UTC)
    duration_seconds = (run_end - run_start).total_seconds()
    logging.info(
        "RUN SUMMARY | window=[%s -> %s] | categories=%d | fetched=%d | ingested=%d "
        "| duration=%.2fs | completed_at=%s",
        start_time, end_time, len(config.log_categories),
        len(raw_records), sent_count, duration_seconds,
        run_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
