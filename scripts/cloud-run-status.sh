#!/usr/bin/env bash
# Checks whether the nyc-dot-cams Cloud Run service is deployed, reachable,
# and whose background rotation loop is actually still producing fresh
# analysis -- not just that the container responds to HTTP. A 200 from
# GET / doesn't prove the rotation_loop() background task is still alive;
# GET /api/status's updated_at age does.
set -uo pipefail

PROJECT_ID="cloudrun-hack26nyc-4392"
REGION="us-central1"
SERVICE_NAME="nyc-dot-cams"
STALE_THRESHOLD_SECONDS=60

echo "Checking Cloud Run service ${SERVICE_NAME} (project=${PROJECT_ID}, region=${REGION})..."
echo ""

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format="value(status.url)" 2>/dev/null)

if [ -z "$URL" ]; then
  echo "NOT DEPLOYED -- no Cloud Run service named ${SERVICE_NAME} found."
  echo "Deploy it with: ./scripts/cloud-run-start.sh"
  exit 1
fi

echo "Deployed: ${URL}"

TOKEN=$(gcloud auth print-identity-token 2>/dev/null)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" --max-time 10 "${URL}/")

case "$HTTP_CODE" in
  200)
    echo "Reachable: GET / -> 200"
    ;;
  403)
    echo "UNREACHABLE -- GET / returned 403 Forbidden."
    echo "Either you're not authenticated as a principal with run.invoker,"
    echo "or the identity token above expired. Try: gcloud auth login"
    exit 1
    ;;
  000)
    echo "UNREACHABLE -- no HTTP response at all (network issue, or the"
    echo "service is scaled to zero and cold-starting slowly -- try again)."
    exit 1
    ;;
  *)
    echo "UNREACHABLE -- GET / returned HTTP ${HTTP_CODE}."
    exit 1
    ;;
esac

STATUS_JSON=$(curl -s -H "Authorization: Bearer ${TOKEN}" --max-time 10 "${URL}/api/status")

echo ""
STATUS_JSON="$STATUS_JSON" STALE_THRESHOLD="$STALE_THRESHOLD_SECONDS" python3 -c "
import json, os, sys, time

raw = os.environ['STATUS_JSON']
stale_threshold = int(os.environ['STALE_THRESHOLD'])

try:
    data = json.loads(raw)
except Exception as e:
    print(f'Could not parse /api/status response: {e}')
    print(raw)
    sys.exit(1)

camera = data.get('camera')
updated_at = data.get('updated_at')

if camera is None:
    print('Background rotation loop has not completed its first cycle yet (camera is null).')
    print('Normal right after a fresh deploy -- wait ~10-15s and check again.')
    sys.exit(0)

age = time.time() - updated_at
print(f\"Last analysis: {camera['name']} ({camera['area']})\")
print(f\"  {data.get('description')}\")
print(f\"  Detected: {data.get('vehicles')}\")
print(f'  {age:.0f}s ago')

if age > stale_threshold:
    print('')
    print(f'WARNING: last analysis is over {stale_threshold}s old (expected ~10s cadence).')
    print('The background rotation loop may have stalled -- check logs:')
    print(f'  gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --project ${PROJECT_ID} --limit 50')
"
