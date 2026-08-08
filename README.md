# NYC DOT Camera Pipeline

Rotates through NYC DOT's public traffic cameras, analyzing each frame with
Gemini for a scene description and Roboflow for vehicle detection, while a
browser tab shows the live image alongside a map of every camera.

No GCP project or cloud hosting involved — just two API keys.

## Setup

```bash
uv sync
```

Create `.env` in the project root:
```
GEMINI_API_KEY=...   # https://aistudio.google.com/apikey
ROBOFLOW_API_KEY=...  # Roboflow dashboard → Settings → Roboflow API Keys
```

## Usage

```bash
uv run main.py
```
(Or `uv run uvicorn main:app --port 8080` — equivalent; `main.py` just
runs uvicorn itself when executed directly, so PyCharm's plain Run button
works too.)

Then open `http://localhost:8080/`. Shows a random camera's image + map
on load; click a different camera on the map to switch to it. Gemini and
Roboflow are only called once per camera you actually select — not on a
timer — since Gemini's free tier is capped at 20 requests/day. Local
only; not deployed anywhere (see `overengineered` branch for the earlier
Cloud Run version, and `git log` for the earlier continuously-polling
version, both retired as more complexity/cost than they were worth for a
personal project).

## Project layout

- `pipeline.py` — NYC DOT / Gemini / Roboflow calls
- `main.py` — the FastAPI server + browser UI

## Next Steps

- [ ] Add CLI arguments for filtering by borough or camera name.
- [ ] Save frames locally or stream to a visualization tool.
