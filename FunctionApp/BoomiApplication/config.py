"""
config.py

Reads and validates all environment variables the connector needs.
Keeping this in one place means function_app.py and every other module
just does `config = Config()` and gets clean, already-validated values.
"""

import os


class Config:
    def __init__(self):
        # --- Boomi API settings ---
        self.base_url = self._require("BOOMI_BASE_URL").rstrip("/")
        self.account_id = self._require("BOOMI_ACCOUNT_ID")
        self.username = self._require("BOOMI_USERNAME")
        self.password = self._require("BOOMI_PASSWORD")

        # Comma-separated list, e.g. "account,as.atom,workspace.user"
        self.log_categories = self._parse_categories(self._require("LOG_CATEGORY"))

        # --- Polling window ---
        self.query_window_minutes = int(os.environ.get("QUERY_WINDOW_MINUTES", "10"))

        # --- Sentinel / Logs Ingestion API settings ---
        # Not required when DRY_RUN=true, since we never call the DCE/DCR in that mode
        # (useful while waiting on the Monitoring Metrics Publisher role assignment).
        self.dry_run = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
        self.dce_endpoint = self._require("DCE_ENDPOINT") if not self.dry_run else os.environ.get("DCE_ENDPOINT", "")
        self.dcr_immutable_id = self._require("DCR_IMMUTABLE_ID") if not self.dry_run else os.environ.get("DCR_IMMUTABLE_ID", "")
        self.dcr_stream_name = os.environ.get("DCR_STREAM_NAME", "Custom-BoomiAppEvents")

        # --- Safety valve ---
        # Caps how many queryMore pages we'll follow in a single run, in case
        # the Boomi API ever misbehaves and keeps returning a queryToken forever.
        self.max_pagination_pages = int(os.environ.get("MAX_PAGINATION_PAGES", "50"))

    @staticmethod
    def _require(name: str) -> str:
        val = os.environ.get(name)
        if val is None or not val.strip():
            raise ValueError(
                f"Required environment variable '{name}' is missing or empty. "
                f"Set it in Function App Application Settings."
            )
        return val.strip()

    @staticmethod
    def _parse_categories(raw: str):
        """Splits comma-separated categories, strips whitespace, and dedupes
        while preserving order (so log output is stable and readable)."""
        seen = set()
        categories = []
        for part in raw.split(","):
            cat = part.strip()
            if cat and cat not in seen:
                seen.add(cat)
                categories.append(cat)
        if not categories:
            raise ValueError("LOG_CATEGORY must contain at least one non-empty category.")
        return categories
