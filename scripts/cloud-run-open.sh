#!/usr/bin/env bash
# Opens the deployed nyc-dot-cams Cloud Run service in the default browser.
# If the service is private (authenticated-only, the default), a plain
# browser tab can't attach an auth header -- this starts
# `gcloud run services proxy` in the background and opens the local proxy
# URL instead, reusing an already-running proxy if one exists.
set -uo pipefail

PROJECT_ID="cloudrun-hack26nyc-4392"
REGION="us-central1"
SERVICE_NAME="nyc-dot-cams"
PROXY_PORT=8081
PROXY_PID_FILE="/tmp/nyc-dot-cams-cloud-run-proxy.pid"
PROXY_LOG_FILE="/tmp/nyc-dot-cams-cloud-run-proxy.log"

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format="value(status.url)" 2>/dev/null)

if [ -z "$URL" ]; then
  echo "NOT DEPLOYED -- no Cloud Run service named ${SERVICE_NAME} found." >&2
  echo "Deploy it with: ./scripts/cloud-run-start.sh" >&2
  exit 1
fi

IS_PUBLIC=$(gcloud run services get-iam-policy "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --format=json 2>/dev/null | grep -c "allUsers" || true)

if [ "$IS_PUBLIC" -gt 0 ]; then
  echo "Service is public: ${URL}"
  echo "Opening in browser..."
  open "$URL"
  exit 0
fi

echo "Service is private (authenticated-only)."

if [ -f "$PROXY_PID_FILE" ] && kill -0 "$(cat "$PROXY_PID_FILE")" 2>/dev/null; then
  echo "Reusing already-running proxy (pid $(cat "$PROXY_PID_FILE"))."
else
  echo "Starting authenticated local proxy on port ${PROXY_PORT}..."
  nohup gcloud run services proxy "$SERVICE_NAME" --region "$REGION" --project "$PROJECT_ID" --port "$PROXY_PORT" > "$PROXY_LOG_FILE" 2>&1 &
  echo $! > "$PROXY_PID_FILE"

  for _ in $(seq 1 15); do
    if curl -s -o /dev/null "http://127.0.0.1:${PROXY_PORT}/" 2>/dev/null; then
      break
    fi
    sleep 1
  done
fi

echo "Opening http://127.0.0.1:${PROXY_PORT}/"
open "http://127.0.0.1:${PROXY_PORT}/"
echo ""
echo "Proxy runs in the background until stopped: kill \$(cat ${PROXY_PID_FILE})"
