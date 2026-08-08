# NYC DOT Camera Pipeline

Rotates through NYC DOT's public traffic cameras, analyzing each frame with
Vertex AI (Gemini) for a scene description and Roboflow for vehicle
detection, while a browser tab shows the live image alongside a map of
every camera.

## Documentation

- [Architecture overview](docs/ARCHITECTURE.md) — technologies, key APIs, module/data-flow diagram
- [Runbook](docs/RUNBOOK.md) — setup, credentials, configuration, troubleshooting, Google Cloud Run and Roboflow explained
- [Code walkthrough](docs/CODE_WALKTHROUGH.md) — function-by-function explanation of `main.py`, including the reasoning behind non-obvious decisions
- [API examples](docs/API_EXAMPLES.md) — real captured request/response payloads from every external API, so the code is understandable even without live Vertex AI/Roboflow access
- [Production readiness](docs/PRODUCTION_READINESS.md) — honest gap analysis: cost, throughput, reliability, observability, security, testing
- [Design: fully local deployment](docs/design/local-deployment.md) — proposal to replace Vertex AI and Roboflow with on-device models (not implemented)
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

## Next Steps

- [ ] Add CLI arguments for filtering by borough or camera name.
- [ ] Save frames locally or stream to a visualization tool.
- [ ] Migrate off the deprecated `vertexai.generative_models` SDK before June 2026.
