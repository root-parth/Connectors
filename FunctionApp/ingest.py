"""
ingest.py

Pushes transformed records to Sentinel via the Logs Ingestion API (DCE/DCR
based — the Data Collector API this replaces was retired). Auth is via
Managed Identity through DefaultAzureCredential — no client secret to
store, rotate, or leak.

The Function App's system-assigned identity must be granted the
"Monitoring Metrics Publisher" role, scoped to the DCR (this is handled
by the ARM template's roleAssignment resource).

LogsIngestionClient.upload() accepts the full list of records in one call
and handles batching internally against the API's payload size limits, so
we don't need to chunk manually here.
"""

import json
import logging

from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient

logger = logging.getLogger("ingest")


class SentinelIngestor:
    def __init__(self, config):
        self.config = config
        if config.dry_run:
            # Skip building any Azure client/credential entirely — this lets you
            # test locally before Managed Identity has the DCR role assigned.
            logger.warning("DRY_RUN is enabled — records will be logged, NOT sent to Sentinel.")
            self.client = None
        else:
            credential = DefaultAzureCredential()
            self.client = LogsIngestionClient(endpoint=config.dce_endpoint, credential=credential)

    def send(self, records: list) -> int:
        if not records:
            logger.info("No records to ingest this run — skipping upload call.")
            return 0

        if self.config.dry_run:
            logger.info("[DRY RUN] Would ingest %d record(s). First record:\n%s",
                        len(records), json.dumps(records[0], indent=2))
            return len(records)

        self.client.upload(
            rule_id=self.config.dcr_immutable_id,
            stream_name=self.config.dcr_stream_name,
            logs=records,
        )

        logger.info(
            "Ingested %d record(s) into stream '%s' via DCR.",
            len(records), self.config.dcr_stream_name,
        )
        return len(records)
