# NYC DOT Camera Pipeline

Rotates through NYC DOT's public traffic cameras, analyzing each frame with
Vertex AI (Gemini) for a scene description and Roboflow for vehicle
detection, while a browser tab shows the live image alongside a map of
every camera.

## Documentation

- [Architecture overview](docs/ARCHITECTURE.md) — technologies, key APIs, module/data-flow diagram
- [Runbook](docs/RUNBOOK.md) — setup, credentials, configuration, troubleshooting, Google Cloud Run and Roboflow explained

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
