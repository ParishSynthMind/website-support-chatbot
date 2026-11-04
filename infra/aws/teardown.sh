#!/usr/bin/env bash
# Remove everything deploy.sh created: function, URL, role, DynamoDB table and log group.
#
#   AWS_REGION=eu-north-1 ./infra/aws/teardown.sh
set -euo pipefail
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-north-1}}"
STACK="${STACK_NAME:-neo-support-chatbot}"
aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK"
echo "Deleted stack $STACK in $REGION. Nothing from it is left running or billing."
