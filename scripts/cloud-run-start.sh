#!/usr/bin/env bash
# Deploys the nyc-dot-cams Cloud Run service.
#
# Costs money continuously while running (--min-instances=1 keeps one
# instance alive, and the background rotation loop makes real, billed
# Gemini + Roboflow calls every 10 seconds the whole time). Run
# scripts/cloud-run-stop.sh when you're done. See docs/RUNBOOK.md#google-cloud-run
# for the full explanation.
set -euo pipefail

cd "$(dirname "$0")/.."

# NOTE: this project ID is from the original hackathon sandbox, whose
# account has since been deleted -- update it to your own GCP project
# before running this script again (only needed to host Cloud Run itself;
# Gemini access no longer depends on this project at all, see below).
PROJECT_ID="cloudrun-hack26nyc-4392"
REGION="us-central1"
SERVICE_NAME="nyc-dot-cams"

if [ ! -f .env ]; then
  echo "Error: .env not found. Create it with GEMINI_API_KEY=... and ROBOFLOW_API_KEY=... first (see docs/RUNBOOK.md#credentials)." >&2
  exit 1
fi

GEMINI_API_KEY=$(grep -E '^GEMINI_API_KEY=' .env | cut -d '=' -f2-)
if [ -z "$GEMINI_API_KEY" ]; then
  echo "Error: GEMINI_API_KEY not set in .env." >&2
  exit 1
fi

ROBOFLOW_API_KEY=$(grep -E '^ROBOFLOW_API_KEY=' .env | cut -d '=' -f2-)
if [ -z "$ROBOFLOW_API_KEY" ]; then
  echo "Error: ROBOFLOW_API_KEY not set in .env." >&2
  exit 1
fi

echo "Deploying $SERVICE_NAME to Cloud Run (project=$PROJECT_ID, region=$REGION)..."
echo "Builds a container from source via Cloud Build — can take a few minutes."
echo ""

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --no-allow-unauthenticated \
  --min-instances=1 \
  --max-instances=1 \
  --memory 1Gi \
  --set-env-vars "GEMINI_API_KEY=${GEMINI_API_KEY},ROBOFLOW_API_KEY=${ROBOFLOW_API_KEY}" \
  --quiet

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format="value(status.url)")

echo ""
echo "Deployed: ${URL}"
echo ""
echo "Private by default (no --allow-unauthenticated). To view it in a browser:"
echo "  gcloud run services proxy ${SERVICE_NAME} --region ${REGION} --project ${PROJECT_ID}"
echo "  then open http://127.0.0.1:8080/"
echo ""
echo "To make it directly reachable without a proxy instead:"
echo "  gcloud run services add-iam-policy-binding ${SERVICE_NAME} --region ${REGION} --project ${PROJECT_ID} --member=allUsers --role=roles/run.invoker"
echo ""
echo "Reminder: this bills continuously until stopped. Run scripts/cloud-run-stop.sh when done."
