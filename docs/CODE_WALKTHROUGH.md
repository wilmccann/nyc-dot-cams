# Code Walkthrough

`main.py` is one file, ~200 lines, no internal module boundaries. This doc
walks through it function by function, explaining *why* it's written the
way it is — including a few non-obvious decisions that came from bugs hit
while building it. Pair this with [API_EXAMPLES.md](API_EXAMPLES.md) (what
the external calls actually return) and
[ARCHITECTURE.md](ARCHITECTURE.md) (the system-level picture). This doc
alone should be enough to understand the code even without Vertex AI or
Roboflow access.

## Imports and module-level setup

```python
load_dotenv()
```

Called at **import time**, before `main()` runs — this is what makes
`ROBOFLOW_API_KEY` available via `os.environ[...]` later without the
caller having to remember to load `.env` themselves. It's a side effect of
just importing the module, which is a little unusual (most code avoids
work at import time) but is the standard `python-dotenv` pattern.

```python
PROJECT_ID = "cloudrun-hack26nyc-4392"
LOCATION = "us-central1"
ROBOFLOW_API_URL = "https://serverless.roboflow.com"
ROBOFLOW_MODEL_ID = "vehicle-detection-3mmwj/1"
```

Hardcoded, not environment-driven. `PROJECT_ID` is tied to a specific
(temporary, hackathon) GCP project — this is the first thing that breaks
once that project access is gone. `ROBOFLOW_MODEL_ID` points at a *public*
Roboflow Universe model, not anything trained for this project — see
[API_EXAMPLES.md](API_EXAMPLES.md#4-roboflow--inferencehttpclientinfer) for
what its output actually looks like.

## `get_cameras()`

```python
def get_cameras():
    url = "https://webcams.nyctmc.org/api/cameras"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching cameras: {e}")
        return []
```

Straightforward GET + JSON parse. `raise_for_status()` turns a bad HTTP
status into an exception, which the `except` immediately catches and turns
into an empty list — so a failed fetch here doesn't crash the app, it just
results in "no cameras," which `main()` checks for and exits cleanly on.

## `filter_online_cameras()`

```python
return [c for c in cameras if str(c.get("isOnline")).lower() == "true"]
```

The `str(...).lower() == "true"` dance exists because the API returns
`isOnline` as the **string** `"true"`, not a JSON boolean `true`. A naive
`if c.get("isOnline")` would be truthy for *any* non-empty string,
including the string `"false"` — that bug would silently include every
offline camera too. Confirmed by looking at the raw API response; see
[API_EXAMPLES.md](API_EXAMPLES.md#1-nyc-dot-camera-list--get-httpswebcamsnyctmcorgapicameras).

## `analyze_frame(model, frame)`

```python
def analyze_frame(model, frame):
    image_part = Part.from_data(frame, mime_type="image/jpeg")
    response = model.generate_content(
        [image_part, "Describe the traffic and road conditions visible in this camera image in one concise sentence."]
    )
    return response.text.strip()
```

Takes an already-constructed `GenerativeModel` (built once in
`poll_camera`, not per-call — creating it is not free) and raw JPEG bytes.
`Part.from_data` wraps bytes for a multimodal prompt; the list
`[image_part, "..."]` is "image, then text instruction," which is how you
mix modalities in a single `generate_content` call.

Only `.text` is used — the response object carries much more (token
counts, finish reason, thinking-token counts). See
[API_EXAMPLES.md](API_EXAMPLES.md#3-vertex-ai--generativemodelgenerate_content)
for the full shape and why that matters for cost.

No check on `finish_reason` — if Gemini ever returns something other than
`STOP` (e.g. blocked by a safety filter), `.text` may not exist and this
would raise, which is caught by the generic `except Exception` one level
up in `poll_camera`.

## `detect_vehicles(roboflow_client, frame)`

```python
def detect_vehicles(roboflow_client, frame):
    image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
    result = roboflow_client.infer(image, model_id=ROBOFLOW_MODEL_ID)
    predictions = result.get("predictions", [])
    counts = {}
    for pred in predictions:
        counts[pred["class"]] = counts.get(pred["class"], 0) + 1
    if not counts:
        return "no vehicles detected"
    return ", ".join(f"{count} {cls}" for cls, count in sorted(counts.items()))
```

The `cv2.imdecode(np.frombuffer(...))` line exists because of a real bug:
passing raw JPEG bytes straight to `.infer()` fails with `Unknown type of
input (bytes) submitted` — the SDK's docs suggest bytes work, they don't
in practice. Decoding to a numpy array (what OpenCV calls a `Mat`, in
BGR channel order) first is required.

The counting logic just tallies `predictions[i]["class"]` — it ignores
bounding box position (`x`, `y`, `width`, `height`) and confidence scores
entirely, treating every returned prediction as equally real. See
[API_EXAMPLES.md](API_EXAMPLES.md#4-roboflow--inferencehttpclientinfer)
for a captured example with real coordinates, which a future feature
(drawing boxes, filtering low-confidence detections) would need to use.

## `open_camera_viewer(all_cams, interval)`

This is the largest function and the only one that doesn't call an
external API — it generates a self-contained HTML file and opens it in
the default browser.

**Why a generated file instead of a template file:** everything the page
needs (the camera list with coordinates and image URLs, the rotation
interval) is Python data that needs to end up as JavaScript data. Rather
than a templating library, it's an f-string with `json.dumps(markers)`
spliced in directly — simple enough at this size that a templating engine
would be overhead, not simplification.

**Why `{{` and `}}` everywhere in the JS:** it's an f-string, so any
literal `{` or `}` meant for JavaScript (every function body, every
object literal) has to be doubled to escape Python's own `{...}`
interpolation syntax. This is the most fragile part of the file to hand-edit
— it's easy to get an escaping level wrong and produce broken JS that
fails silently (the page just won't work, no Python-side error).

**Why the browser does its own rotation instead of Python telling it what
to show:** there's no server and no persistent connection between the
Python process and the browser tab — `webbrowser.open()` just launches a
static file once. So the full camera list (with `imageUrl`, `lat`, `lon`,
`area` for every camera) is embedded into the page up front, and the
page's own `setInterval` independently walks through it. This is also why
Python's rotation (in `poll_camera`) and the browser's rotation can drift
out of sync over a long run — they're two separate timers with no
communication channel. See the note in
[ARCHITECTURE.md](ARCHITECTURE.md#important-design-note-two-independent-rotation-loops).

**Why Leaflet + OpenStreetMap and not an embedded NYC DOT map:** the real
`webcams.nyctmc.org/map` page sends `X-Frame-Options: DENY`, confirmed by
checking its response headers directly — it cannot be iframed, full stop.
Leaflet + OSM tiles is a free, no-API-key alternative loaded from a CDN
inside the generated page.

**Why a temp file:** `tempfile.mkstemp(suffix=".html")` avoids cluttering
the project directory and guarantees a unique filename per run (so
rotation state from a previous run's leftover file, if any, can never be
opened by mistake — every run gets a fresh file).

## `poll_camera(all_cams, interval=10)`

The orchestration loop. Three things happen once, before the loop starts:
1. `open_camera_viewer(all_cams, interval)` — opens the browser tab.
2. `vertexai.init(...)` + `GenerativeModel(...)` — one Gemini client, reused every iteration.
3. `InferenceHTTPClient(...)` — one Roboflow client, reused every iteration.

Reusing clients across iterations (rather than constructing them inside
the loop) avoids repeated auth/setup overhead per camera.

Then the loop:
```python
idx = 0
while True:
    cam = all_cams[idx]
    # fetch cam's frame, analyze it, print results
    idx = (idx + 1) % len(all_cams)
    time.sleep(interval)
```

One camera is fully processed — fetched, described by Gemini, scanned by
Roboflow, printed — **per `interval` seconds**, not per camera per second.
With ~963 online cameras and a 10s interval, a full pass through every
camera takes roughly `963 × (10s + processing time)` ≈ **2.5–3 hours**.
Whether that cadence is acceptable depends entirely on what the app is
for — see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md#throughput--the-963-camera-problem)
for the scaling implications of that number.

Two separate `except` blocks distinguish network failures
(`requests.RequestException`, e.g. the camera's image endpoint timing out)
from everything else (`Exception`, which covers both Gemini and Roboflow
failures) — both just print and move on to the next camera rather than
stopping the loop, since one bad camera shouldn't take down the whole
rotation.

`KeyboardInterrupt` (Ctrl+C) is the only intended way to stop — caught
around the `while True`, printing a clean "Polling stopped." message
instead of a stack trace.

## `main()`

```python
def main():
    cams = get_cameras()
    online = filter_online_cameras(cams)
    if not online:
        print("No online cameras found.")
        return
    boroughs = sorted(list(set(c.get("area") for c in online if c.get("area"))))
    print(f"Available boroughs: {', '.join(boroughs)}")
    poll_camera(online)
```

Entry point. The `boroughs` line computes and prints available boroughs
but nothing in the code lets you actually filter by one — it's informational
only right now (matches the "Add CLI arguments for filtering by borough"
item still open in the README's Next Steps).
