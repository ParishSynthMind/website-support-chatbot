"""AWS Lambda entry point: the same FastAPI app behind a Lambda Function URL.

Mangum turns the Function URL event into an ASGI request, so main.py runs unchanged.
What differs on Lambda is state: instances come and go, so the hard cost limits live
in DynamoDB, where every instance sees the same counters:

- a daily cap on model calls (DAILY_MODEL_CALL_CAP), taken atomically before each call;
- the monthly spend cap from main.py, now summed across all instances.

Handover leads still go to SQLite, which on Lambda is /tmp and so short-lived; with
NOTIFIER=console each lead is also written to CloudWatch Logs, which is the record."""
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .store import Store

log = logging.getLogger("support_chatbot")


class DynamoUsageStore(Store):
    """Store whose usage counters live in one DynamoDB table (partition key "pk").

    Items: "day#YYYY-MM-DD" holds the day's model-call count (expires after 40 days);
    "month#YYYY-MM" holds requests, tokens and cost for the month."""

    def __init__(self, path: Path, table_name: str, daily_cap: int, client=None, clock=None):
        super().__init__(path)
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self.client = client
        self.table = table_name
        self.daily_cap = daily_cap
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def allow_model_call(self) -> bool:
        """Count this call against today's cap. One conditional update, so two
        instances can't both take the last slot. Fails closed: if DynamoDB can't
        be reached, no model call is made."""
        if self.daily_cap <= 0:
            return False
        now = self.clock()
        expires = int((now + timedelta(days=40)).timestamp())
        try:
            self.client.update_item(
                TableName=self.table,
                Key={"pk": {"S": "day#" + now.strftime("%Y-%m-%d")}},
                UpdateExpression="ADD calls :one SET expires_at = :exp",
                ConditionExpression="attribute_not_exists(calls) OR calls < :cap",
                ExpressionAttributeValues={":one": {"N": "1"}, ":cap": {"N": str(self.daily_cap)},
                                           ":exp": {"N": str(expires)}},
            )
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False
        except Exception:
            log.exception("Daily cap check failed; refusing the model call")
            return False

    def month_spend(self, month: Optional[str] = None) -> float:
        month = month or self.clock().strftime("%Y-%m")
        try:
            item = self.client.get_item(TableName=self.table, Key={"pk": {"S": "month#" + month}},
                                        ConsistentRead=True).get("Item") or {}
        except Exception:
            log.exception("Spend lookup failed; treating the cap as reached")
            return float("inf")
        return float(item.get("cost_usd", {}).get("N", "0"))

    def record_usage(self, input_tokens: int, output_tokens: int, cost_usd: float, month: Optional[str] = None) -> None:
        month = month or self.clock().strftime("%Y-%m")
        try:
            self.client.update_item(
                TableName=self.table,
                Key={"pk": {"S": "month#" + month}},
                UpdateExpression="ADD requests :one, input_tokens :i, output_tokens :o, cost_usd :c",
                ExpressionAttributeValues={":one": {"N": "1"}, ":i": {"N": str(input_tokens)},
                                           ":o": {"N": str(output_tokens)},
                                           ":c": {"N": str(Decimal(str(round(cost_usd, 8))))}},
            )
        except Exception:  # the visitor already has their answer; the daily cap still holds
            log.exception("Recording usage failed")


_handler = None


def build_handler(settings=None, store=None, answerer=None, notifier=None):
    """Create the app once per Lambda instance (cold start) and wrap it for Lambda."""
    from mangum import Mangum

    from .config import Settings
    from .main import create_app

    settings = settings or Settings.from_env()
    if store is None:
        store = DynamoUsageStore(settings.database_path, os.environ["CAP_TABLE"],
                                 int(os.environ.get("DAILY_MODEL_CALL_CAP", "50")))
    app = create_app(settings, answerer=answerer, notifier=notifier, store=store)
    return Mangum(app, lifespan="off")


def handler(event, context):
    global _handler
    if _handler is None:
        logging.getLogger().setLevel(logging.INFO)
        _handler = build_handler()
    return _handler(event, context)
