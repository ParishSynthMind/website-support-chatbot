"""The AWS path, with every AWS call stubbed (botocore Stubber), so no credentials or
network are needed: Claude on Bedrock behind the same interface, the DynamoDB-backed
daily cap and spend cap, the Lambda handler, and the CloudFormation template's guardrails."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
import yaml
from botocore.stub import ANY, Stubber

from app.aws_lambda import DynamoUsageStore, build_handler
from app.config import Settings
from app.kb import KnowledgeBase
from app.llm import PROVIDERS, SYSTEM_PROMPT, BedrockAnswerer, answer_schema, make_answerer
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = {"status": "answered", "answer": "Growth is $49 a month.", "citations": [1]}
NOON = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def aws_client(service):
    return boto3.client(service, region_name="eu-north-1", aws_access_key_id="testing",
                        aws_secret_access_key="testing")


def converse_reply(text=None, stop="end_turn"):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text or json.dumps(PAYLOAD)}]}},
            "stopReason": stop, "usage": {"inputTokens": 1500, "outputTokens": 60, "totalTokens": 1560},
            "metrics": {"latencyMs": 900}}


def hits(question="Growth plan price"):
    return KnowledgeBase.from_dir(Settings().knowledge_base_dir).search(question, 3)


# ---------- Claude on Bedrock ----------

def test_bedrock_sends_the_same_prompt_and_schema_as_the_other_providers():
    client = aws_client("bedrock-runtime")
    with Stubber(client) as stub:
        stub.add_response("converse", converse_reply(), {
            "modelId": "eu.anthropic.claude-haiku-5-5",
            "system": [{"text": SYSTEM_PROMPT.format(company="Orbitly")}],
            "messages": ANY, "inferenceConfig": {"maxTokens": 600},
            "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
                "name": "support_answer", "schema": json.dumps(answer_schema(5))}}}},
            "additionalModelRequestFields": {"output_config": {"effort": "low"}},
        })
        result = BedrockAnswerer("Orbitly", 5, max_tokens=600, client=client).answer(
            "Growth price?", [{"role": "visitor", "text": "hi"}], hits())
    assert result.status == "answered" and result.citations == [1]
    assert (result.input_tokens, result.output_tokens) == (1500, 60)


def test_bedrock_user_message_carries_docs_history_and_question_in_order():
    client = aws_client("bedrock-runtime")
    seen = {}
    client.meta.events.register("provide-client-params.bedrock-runtime.Converse",
                                lambda params, **kw: seen.update(params))
    with Stubber(client) as stub:
        stub.add_response("converse", converse_reply())
        BedrockAnswerer("Orbitly", 5, client=client).answer("Growth price?", [{"role": "visitor", "text": "hi"}], hits())
    user = seen["messages"][0]["content"][0]["text"]
    assert user.index("<knowledge_base>") < user.index("<conversation_history>") < user.index("<visitor_question>")
    assert '<document id="1" source="pricing.md"' in user and "visitor: hi" in user


@pytest.mark.parametrize("stop", ["content_filtered", "guardrail_intervened"])
def test_bedrock_filtered_reply_becomes_a_handover(stop):
    client = aws_client("bedrock-runtime")
    with Stubber(client) as stub:
        stub.add_response("converse", converse_reply(text="", stop=stop))
        result = BedrockAnswerer("Orbitly", 5, client=client).answer("x", [], hits())
    assert result.status == "needs_human" and result.citations == []


@pytest.mark.parametrize("reply", [converse_reply(stop="max_tokens"), converse_reply(text="{not json")])
def test_bedrock_broken_replies_raise_so_chat_falls_back_to_handover(reply):
    client = aws_client("bedrock-runtime")
    with Stubber(client) as stub:
        stub.add_response("converse", reply)
        with pytest.raises(Exception):
            BedrockAnswerer("Orbitly", 5, client=client).answer("x", [], hits())


def test_bedrock_access_denied_turns_into_the_unavailable_reply(tmp_path):
    client = aws_client("bedrock-runtime")
    settings = Settings(database_path=tmp_path / "t.sqlite3", model_provider="bedrock",
                        llm_model="eu.anthropic.claude-haiku-5-5")
    app = create_app(settings, answerer=make_answerer(settings, client=client),
                     notifier=SimpleNamespace(notify=lambda lead: None))
    from fastapi.testclient import TestClient
    with Stubber(client) as stub:
        stub.add_client_error("converse", "AccessDeniedException", "not allowed", 403)
        body = TestClient(app).post("/chat", json={"message": "How much is the Growth plan per month?"}).json()
    assert body["status"] == "unavailable" and body["handover_reason"] == "model_error"


def test_bedrock_provider_env_needs_no_api_key(monkeypatch):
    for k in ("LLM_MODEL", "PRICE_INPUT_PER_MTOK", "PRICE_OUTPUT_PER_MTOK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    s = Settings.from_env()
    assert s.llm_model == "eu.anthropic.claude-haiku-5-5"
    assert (s.price_input_per_mtok, s.price_output_per_mtok) == PROVIDERS["bedrock"][2:4]
    assert PROVIDERS["bedrock"][4] is None


# ---------- DynamoDB cost caps ----------

def make_store(tmp_path, client, cap=2):
    return DynamoUsageStore(tmp_path / "t.sqlite3", "neo-support-chatbot-usage", cap, client=client,
                            clock=lambda: NOON)


def test_daily_cap_takes_a_slot_atomically_and_refuses_when_full(tmp_path):
    ddb = aws_client("dynamodb")
    expected = {"TableName": "neo-support-chatbot-usage", "Key": {"pk": {"S": "day#2026-11-04"}},
                "UpdateExpression": "ADD calls :one SET expires_at = :exp",
                "ConditionExpression": "attribute_not_exists(calls) OR calls < :cap",
                "ExpressionAttributeValues": {":one": {"N": "1"}, ":cap": {"N": "2"}, ":exp": ANY}}
    with Stubber(ddb) as stub:
        stub.add_response("update_item", {}, expected)
        stub.add_client_error("update_item", "ConditionalCheckFailedException", "full", 400)
        store = make_store(tmp_path, ddb)
        assert store.allow_model_call() is True
        assert store.allow_model_call() is False


def test_daily_cap_fails_closed_when_dynamodb_errors(tmp_path):
    ddb = aws_client("dynamodb")
    with Stubber(ddb) as stub:
        stub.add_client_error("update_item", "ProvisionedThroughputExceededException", "slow down", 400)
        assert make_store(tmp_path, ddb).allow_model_call() is False


def test_zero_cap_means_no_model_calls_at_all(tmp_path):
    assert make_store(tmp_path, aws_client("dynamodb"), cap=0).allow_model_call() is False


def test_month_spend_reads_and_records_in_dynamodb(tmp_path):
    ddb = aws_client("dynamodb")
    with Stubber(ddb) as stub:
        stub.add_response("get_item", {"Item": {"pk": {"S": "month#2026-11"}, "cost_usd": {"N": "0.42"}}},
                          {"TableName": "neo-support-chatbot-usage", "Key": {"pk": {"S": "month#2026-11"}},
                           "ConsistentRead": True})
        stub.add_response("update_item", {}, {
            "TableName": "neo-support-chatbot-usage", "Key": {"pk": {"S": "month#2026-11"}},
            "UpdateExpression": "ADD requests :one, input_tokens :i, output_tokens :o, cost_usd :c",
            "ExpressionAttributeValues": {":one": {"N": "1"}, ":i": {"N": "1500"}, ":o": {"N": "60"},
                                          ":c": {"N": "0.00018"}}})
        store = make_store(tmp_path, ddb)
        assert store.month_spend() == pytest.approx(0.42)
        store.record_usage(1500, 60, 0.00018)


def test_month_spend_lookup_failure_counts_as_cap_reached(tmp_path):
    ddb = aws_client("dynamodb")
    with Stubber(ddb) as stub:
        stub.add_client_error("get_item", "InternalServerError", "boom", 500)
        assert make_store(tmp_path, ddb).month_spend() == float("inf")


# ---------- Lambda handler (Function URL event, end to end through FastAPI) ----------

def url_event(method, path, body=None):
    return {"version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
            "headers": {"content-type": "application/json", "host": "abc.lambda-url.eu-north-1.on.aws"},
            "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1",
                                        "sourceIp": "203.0.113.9", "userAgent": "pytest"},
                               "domainName": "abc.lambda-url.eu-north-1.on.aws", "stage": "$default",
                               "requestId": "r1", "accountId": "anonymous", "apiId": "abc",
                               "time": "04/Nov/2026:12:00:00 +0000", "timeEpoch": 0},
            "body": json.dumps(body) if body is not None else None, "isBase64Encoded": False}


class LambdaContext:
    function_name, memory_limit_in_mb, aws_request_id = "neo-support-chatbot", 512, "r1"
    invoked_function_arn = "arn:aws:lambda:eu-north-1:123456789012:function:neo-support-chatbot"

    def get_remaining_time_in_millis(self):
        return 30000


class CappedStore(DynamoUsageStore):
    """DynamoDB store with the AWS calls replaced by a local counter."""

    def __init__(self, path, cap):
        super(DynamoUsageStore, self).__init__(path)
        self.daily_cap, self.calls, self.spend = cap, 0, 0.0

    def allow_model_call(self):
        if self.calls >= self.daily_cap:
            return False
        self.calls += 1
        return True

    def month_spend(self, month=None):
        return self.spend

    def record_usage(self, input_tokens, output_tokens, cost_usd, month=None):
        self.spend += cost_usd


def test_lambda_handler_serves_health_and_chat_and_enforces_the_daily_cap(tmp_path):
    from tests.conftest import FakeAnswerer

    settings = Settings(database_path=tmp_path / "t.sqlite3", model_provider="bedrock",
                        llm_model="eu.anthropic.claude-haiku-5-5")
    answerer = FakeAnswerer()
    handler = build_handler(settings, store=CappedStore(settings.database_path, cap=1), answerer=answerer,
                            notifier=SimpleNamespace(notify=lambda lead: None))

    health = handler(url_event("GET", "/health"), LambdaContext())
    assert health["statusCode"] == 200 and json.loads(health["body"])["provider"] == "bedrock"

    ask = url_event("POST", "/chat", {"message": "How much is the Growth plan per month?"})
    first = json.loads(handler(ask, LambdaContext())["body"])
    second = json.loads(handler(ask, LambdaContext())["body"])
    assert first["status"] == "answered"
    assert second["status"] == "unavailable" and second["handover_reason"] == "daily_cap"
    assert len(answerer.calls) == 1  # the capped request never reached the model


# ---------- CloudFormation template guardrails ----------

TEMPLATE = yaml.safe_load((ROOT / "infra" / "aws" / "template.yaml").read_text())
HOURLY_BILLED = {"AWS::EC2::NatGateway", "AWS::ElasticLoadBalancingV2::LoadBalancer", "AWS::EC2::Instance",
                 "AWS::RDS::DBInstance", "AWS::AppRunner::Service", "AWS::EC2::VPC", "AWS::ECS::Service"}


def test_template_uses_only_pay_per_use_resources():
    types = {r["Type"] for r in TEMPLATE["Resources"].values()}
    assert not types & HOURLY_BILLED
    table = TEMPLATE["Resources"]["CapTable"]["Properties"]
    assert table["ProvisionedThroughput"] == {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1}


def test_every_taggable_resource_is_tagged_project_neo_portfolio():
    for name, res in TEMPLATE["Resources"].items():
        if res["Type"] in ("AWS::Lambda::Url", "AWS::Lambda::Permission"):
            continue  # these resource types take no tags
        assert {"Key": "project", "Value": "neo-portfolio"} in res["Properties"]["Tags"], name


def test_function_role_is_least_privilege():
    statements = TEMPLATE["Resources"]["FunctionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    actions = {a for s in statements for a in s["Action"]}
    assert actions == {"logs:CreateLogStream", "logs:PutLogEvents", "dynamodb:GetItem", "dynamodb:UpdateItem",
                       "bedrock:InvokeModel"}
    assert all("*" not in a for a in actions)


def test_cost_caps_are_wired_into_the_function():
    env = TEMPLATE["Resources"]["Function"]["Properties"]["Environment"]["Variables"]
    assert env["MODEL_PROVIDER"] == "bedrock"
    assert {"DAILY_MODEL_CALL_CAP", "MONTHLY_SPEND_CAP_USD", "LLM_MAX_TOKENS", "CAP_TABLE"} <= set(env)
    params = TEMPLATE["Parameters"]
    assert params["DailyModelCallCap"]["Default"] <= 100 and params["MaxTokens"]["Default"] <= 1000
