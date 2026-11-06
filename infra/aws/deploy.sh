#!/usr/bin/env bash
# Deploy (or update) the chatbot on AWS Lambda (Claude on Amazon Bedrock by default).
#
#   AWS_REGION=eu-north-1 ./infra/aws/deploy.sh
#
# Needs: the AWS CLI with credentials allowed to manage the stack, Python 3 with pip,
# and the Anthropic models enabled for your account in the Bedrock console.
# Optional env: STACK_NAME (default neo-support-chatbot), PERMISSIONS_BOUNDARY_ARN,
# MODEL_ID, DAILY_MODEL_CALL_CAP, MONTHLY_SPEND_CAP_USD, MAX_TOKENS.
# To answer with Gemini or the Anthropic API instead of Bedrock (e.g. while a new
# account's Bedrock quota is still 0): MODEL_PROVIDER=gemini PROVIDER_API_KEY=...
set -euo pipefail
cd "$(dirname "$0")/../.."

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-north-1}}"
STACK="${STACK_NAME:-neo-support-chatbot}"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

echo "1/4 Building the Lambda package (arm64, Python 3.12)"
python3 -m pip install --quiet --target "$BUILD/pkg" --platform manylinux2014_aarch64 \
  --implementation cp --python-version 3.12 --only-binary=:all: -r infra/aws/requirements-lambda.txt
cp -R app knowledge_base widget demo "$BUILD/pkg/"
find "$BUILD/pkg" -name __pycache__ -type d -prune -exec rm -rf {} +
(cd "$BUILD/pkg" && zip -qr9 "$BUILD/function.zip" .)
echo "    package: $(du -h "$BUILD/function.zip" | cut -f1)"

echo "2/4 Creating or updating the CloudFormation stack $STACK in $REGION"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/aws/template.yaml --capabilities CAPABILITY_NAMED_IAM \
  --tags project=neo-portfolio --no-fail-on-empty-changeset \
  --parameter-overrides \
    "FunctionName=$STACK" \
    "ModelProvider=${MODEL_PROVIDER:-bedrock}" \
    "ProviderApiKey=${PROVIDER_API_KEY:-}" \
    "PermissionsBoundaryArn=${PERMISSIONS_BOUNDARY_ARN:-}" \
    "ModelId=${MODEL_ID:-eu.anthropic.claude-haiku-5-5}" \
    "DailyModelCallCap=${DAILY_MODEL_CALL_CAP:-50}" \
    "MonthlySpendCapUsd=${MONTHLY_SPEND_CAP_USD:-1}" \
    "MaxTokens=${MAX_TOKENS:-600}"

echo "3/4 Uploading the code"
aws lambda update-function-code --region "$REGION" --function-name "$STACK" \
  --zip-file "fileb://$BUILD/function.zip" --query 'CodeSize' --output text >/dev/null
aws lambda wait function-updated-v2 --region "$REGION" --function-name "$STACK"

URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue" --output text)"
echo "4/4 Live at $URL"
echo "    check it:  python3 scripts/check_live.py $URL --chat"
echo "    remove it: ./infra/aws/teardown.sh"
