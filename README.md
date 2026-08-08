# NYC DOT Camera Pipeline

Rotates through NYC DOT's public traffic cameras, analyzing each frame with
Vertex AI (Gemini) for a scene description and Roboflow for vehicle
detection, while a browser tab shows the live image alongside a map of
every camera. Runs either as a local script (`main.py`) or as a Cloud Run
web service (`app.py`) — see [Cloud Run service mode](#cloud-run-service-mode) below.

## Documentation

- [Architecture overview](docs/ARCHITECTURE.md) — technologies, key APIs (including the ones this project now exposes itself), module/data-flow diagrams for both entry points
- [Runbook](docs/RUNBOOK.md) — setup, credentials, configuration, troubleshooting, and the real Cloud Run deploy steps (including the IAM issues actually hit)
- [Code walkthrough](docs/CODE_WALKTHROUGH.md) — function-by-function explanation of `pipeline.py`, `main.py`, and `app.py`, including the reasoning behind non-obvious decisions
- [API examples](docs/API_EXAMPLES.md) — real captured request/response payloads from every external API, plus this project's own `/api/status`, so the code is understandable even without live Vertex AI/Roboflow access
- [Production readiness](docs/PRODUCTION_READINESS.md) — honest gap analysis: cost, throughput, reliability, observability, security, testing
- [Design: fully local deployment](docs/design/local-deployment.md) — proposal to replace Vertex AI and Roboflow with on-device models (not implemented)
- [Design: Cloud Run deployment](docs/design/cloud-run-deployment.md) — the design `app.py` implements; **implemented and verified working on Cloud Run**, plus a not-implemented batch-pipeline alternative and an unresolved known limitation
- [Changelog](docs/CHANGELOG.md) — what was built, commit by commit

## Setup

This project uses `uv` for dependency management. See the
[Runbook](docs/RUNBOOK.md#credentials) for the full credential setup
(Google Vertex AI + Roboflow API key).

```bash
uv sync
```

## Usage

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/keys/google-key.json
uv run main.py
```

Opens a browser tab (live camera image + map) and rotates through every
online camera every 10 seconds, printing a Gemini description and Roboflow
vehicle count for each in the terminal. `Ctrl+C` to stop.

### Cloud Run service mode

`app.py` is a FastAPI implementation of the design in
[docs/design/cloud-run-deployment.md](docs/design/cloud-run-deployment.md):
the image and map stay entirely client-side (unchanged from `main.py`'s
viewer), while a background loop on the server runs the Gemini/Roboflow
analysis — the only part that needs credentials — and exposes it at
`/api/status` for the page to poll. **This has been deployed to Cloud Run
and verified working end-to-end** — see
[RUNBOOK.md](docs/RUNBOOK.md#google-cloud-run) for the exact deploy
command, the IAM issues actually hit along the way, and how to tear it
back down.

Run it locally:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/keys/google-key.json
uv run uvicorn app:app --port 8080
```
Then open `http://localhost:8080/`.

Deploy it:
```bash
gcloud run deploy nyc-dot-cams --source . --region us-central1 \
  --no-allow-unauthenticated --min-instances=1 --max-instances=1 --memory 1Gi \
  --set-env-vars ROBOFLOW_API_KEY=your_key_here
```
See the Runbook for what `--min-instances=1`/`--max-instances=1` are
protecting against, and **don't leave a deployment running unattended** —
it makes real, continuously-billed Vertex AI/Roboflow calls the whole time
it's up (`gcloud run services delete nyc-dot-cams --region us-central1`
to tear down).

Known limitation, not yet fixed: each browser tab rotates its own
displayed image independently of the server's single shared analysis
loop, so the analysis panel can show a materially different camera than
the one currently pictured — the page labels this explicitly rather than
implying they're in sync. Root cause and three possible future fixes are
detailed in
[design/cloud-run-deployment.md](docs/design/cloud-run-deployment.md#known-limitation-found-during-implementation-image-and-analysis-can-point-at-different-cameras).

## Next Steps

- [ ] Fix the image/analysis camera-mismatch limitation in `app.py` (see above).
- [ ] Move `app.py`'s Roboflow key from `--set-env-vars` to Secret Manager for anything beyond a one-off verification deploy.
- [ ] Add CLI arguments for filtering by borough or camera name.
- [ ] Save frames locally or stream to a visualization tool.
- [ ] Migrate off the deprecated `vertexai.generative_models` SDK before June 2026.
