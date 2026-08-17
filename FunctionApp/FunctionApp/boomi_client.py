"""
boomi_client.py

Handles talking to Boomi's AuditLog API:
  1. Build and Get the query filter body — single category uses a plain
     EQUALS filter; 2+ categories uses the OR-nested filter so we fetch
     every category in ONE call instead of looping per category.
  2. Follow pagination via queryMore, which (per Boomi's docs) expects the
     token as a raw text/plain body, not JSON.
"""

import logging
import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger("boomi_client")


class BoomiClient:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(config.username, config.password)
        # Boomi defaults to XML if Accept isn't explicit — force JSON on every call.
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.query_url = f"{config.base_url}/api/rest/v1/{config.account_id}/AuditLog/query"
        self.query_more_url = f"{config.base_url}/api/rest/v1/{config.account_id}/AuditLog/queryMore"

    def build_query_filter(self, start_time: str, end_time: str) -> dict:
        """Builds the QueryFilter body. Single category -> simple EQUALS.
        Multiple categories -> OR-nested EQUALS block, same shape as Boomi's
        multi-value filter syntax."""
        categories = self.config.log_categories

        date_filter = {
            "argument": [start_time, end_time],
            "operator": "BETWEEN",
            "property": "date",
        }

        if len(categories) == 1:
            type_filter = {
                "argument": [categories[0]],
                "operator": "EQUALS",
                "property": "type",
            }
        else:
            type_filter = {
                "operator": "or",
                "nestedExpression": [
                    {"argument": [category], "operator": "EQUALS", "property": "type"}
                    for category in categories
                ],
            }

        return {
            "QueryFilter": {
                "expression": {
                    "operator": "and",
                    "nestedExpression": [type_filter, date_filter],
                }
            }
        }

    @staticmethod
    def _parse_json_response(resp: requests.Response, context: str) -> dict:
        """Raises with full diagnostic detail (status, content-type, body
        snippet) instead of a bare JSONDecodeError, so a bad response is
        actually debuggable instead of a mystery."""
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            logger.error(
                "Boomi API HTTP error during %s | status=%s | content-type=%s | body(first 500 chars)=%r",
                context, resp.status_code, resp.headers.get("Content-Type"), resp.text[:500],
            )
            raise

        try:
            return resp.json()
        except ValueError:
            logger.error(
                "Boomi API returned a non-JSON response during %s | status=%s | content-type=%s | "
                "url=%s | body(first 500 chars)=%r",
                context, resp.status_code, resp.headers.get("Content-Type"), resp.url, resp.text[:500],
            )
            raise

    def fetch_all(self, start_time: str, end_time: str) -> list:
        """Runs the initial query, then follows queryToken pagination until
        exhausted or max_pagination_pages is hit. Returns the full list of
        raw AuditLog records for the window."""
        all_records = []
        body = self.build_query_filter(start_time, end_time)

        logger.info(
            "Querying Boomi AuditLog | categories=%s | window=%s to %s",
            self.config.log_categories, start_time, end_time,
        )

        resp = self.session.post(self.query_url, json=body, timeout=60)
        data = self._parse_json_response(resp, context="initial query")

        page_num = 1
        records = data.get("result", []) or []
        all_records.extend(records)
        logger.info(
            "Page %d: %d record(s) received (API reports numberOfResults=%s)",
            page_num, len(records), data.get("numberOfResults"),
        )

        query_token = data.get("queryToken")
        while query_token:
            if page_num >= self.config.max_pagination_pages:
                logger.warning(
                    "Hit MAX_PAGINATION_PAGES=%d — stopping pagination early. "
                    "If this happens regularly, raise the limit.",
                    self.config.max_pagination_pages,
                )
                break

            page_num += 1
            resp = self.session.post(
                self.query_more_url,
                data=query_token.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=60,
            )
            data = self._parse_json_response(resp, context=f"queryMore page {page_num}")

            records = data.get("result", []) or []
            all_records.extend(records)
            logger.info("Page %d: %d record(s) received", page_num, len(records))

            query_token = data.get("queryToken")

        logger.info(
            "Fetch complete | total_records=%d | pages=%d | categories=%s",
            len(all_records), page_num, self.config.log_categories,
        )
        return all_records
