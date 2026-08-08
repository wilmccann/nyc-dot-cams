# Changelog

Built in a single evening session (2026-08-07) ahead of a 10pm demo. Entries
are grouped by commit, oldest first.

## `86a9e00` — Initial DOT camera pipeline

Starting point: fetch cameras from the NYC DOT API, filter to online ones,
poll the first online camera's image URL in a loop, print byte counts.
No AI analysis yet — just a placeholder comment for future Roboflow
inference.

## `1946df4` — Add Vertex AI and Roboflow inference to camera polling loop

Each polled frame now gets a Gemini-generated traffic description (Vertex
AI) and a vehicle count (Roboflow hosted inference), replacing the
placeholder. Credentials set up via Application Default Credentials
instead of a downloaded service-account key, after a service-account role
grant was blocked by an IAM deny-policy on the sandboxed GCP project.
Added `python-dotenv` so `ROBOFLOW_API_KEY` loads from a local `.env`
file automatically.

## `1226e26` — Open a live-refreshing browser view of the polled camera

Writes a small local HTML page with a JS-driven auto-refreshing `<img>`
tag pointed at the camera's image endpoint, opened once via
`webbrowser.open()` when polling starts.

## `7f243c3` — Add map pane showing all camera locations to the browser viewer

Splits the viewer page into the live camera feed and a Leaflet/OSM map
plotting every camera's lat/lon, with the currently polled camera
highlighted as a distinct marker. Embedding the official nyctmc.org map
wasn't possible (`X-Frame-Options: DENY`), so this builds a lightweight
equivalent from data already returned by the API.

## `eb120ab` — Rotate through all online cameras instead of polling one

`poll_camera` now cycles the full online-camera list every interval,
analyzing a different camera's frame each tick instead of the same
`cam = online[0]` forever. The browser viewer rotates its image, title,
and map highlight marker on a matching client-side timer, embedding each
camera's `imageUrl`/lat/lon/area up front so no page reload is needed
between cameras.

## `786b83b` — Add architecture overview and runbook docs

`docs/ARCHITECTURE.md` covers the tech stack, key APIs, and a
module/data-flow diagram. `docs/RUNBOOK.md` covers credential setup (and
why ADC was used instead of a service-account key), running the app,
configuration, a Cloud Run and Roboflow primer, and a troubleshooting log
built from issues actually hit while building this. README updated to
match current behavior and link the docs.
