#!/usr/bin/env bash
# Tears down the nyc-dot-cams Cloud Run service to stop ongoing billing.
# Redeploying later is just scripts/cloud-run-start.sh again — this deletes
# the live running instance, not any code or config.
set -euo pipefail

PROJECT_ID="cloudrun-hack26nyc-4392"
REGION="us-central1"
SERVICE_NAME="nyc-dot-cams"

echo "Deleting Cloud Run service ${SERVICE_NAME} (project=${PROJECT_ID}, region=${REGION})..."
gcloud run services delete "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --quiet
echo "Deleted. No further Cloud Run compute or API charges from this service."
