# Code Walkthrough

Three files now, not one: **`pipeline.py`** (shared NYC DOT/Gemini/Roboflow
logic), **`main.py`** (the original local script), and **`app.py`** (the
Cloud Run service added later, covering the same ground over HTTP instead
of a local browser tab). This doc walks through all three, explaining
*why* each is written the way it is — including non-obvious decisions
that came from bugs hit while building them. Pair this with
[API_EXAMPLES.md](API_EXAMPLES.md) (what the external calls actually
return) and [ARCHITECTURE.md](ARCHITECTURE.md) (the system-level picture,
including a diagram of how these three files relate). This doc alone
should be enough to understand the code even without Gemini or Roboflow
access.

## `pipeline.py` — shared logic

Both entry points import from here rather than duplicating this code.
This module doesn't do anything on its own; nothing in it opens a browser,
starts a server, or runs a loop — it's pure "given inputs, call an
external API, return a result" functions plus two small client builders.

```python
load_dotenv()
```

Wait — this line is actually **not** in `pipeline.py`. It's called
separately in both `main.py` and `app.py`, near their own top-level
imports, not once centrally in `pipeline.py`. That's deliberate: whichever
file is actually the *entry point* being run is responsible for loading
`.env`, since `pipeline.py` might in principle be imported by something
else later that manages its own environment differently (a test suite,
for instance). It's a minor redundancy (two `load_dotenv()` calls across
the codebase instead of one) traded for not making the shared module have
an import-time side effect that isn't obviously its job.

```python
ROBOFLOW_API_URL = "https://serverless.roboflow.com"
ROBOFLOW_MODEL_ID = "vehicle-detection-3mmwj/1"
```

Hardcoded, not environment-driven, and centralized here instead of
duplicated in both entry points. `ROBOFLOW_MODEL_ID` points at a *public*
Roboflow Universe model, not anything trained for this project — see
[API_EXAMPLES.md](API_EXAMPLES.md#4-roboflow--inferencehttpclientinfer)
for what its output actually looks like.

There used to be a `PROJECT_ID`/`LOCATION` pair here too, for Vertex AI.
The original version of this doc flagged them as "the first thing that
breaks once that project access is gone" — which is exactly what
happened (the hackathon account backing that project was deleted), and
why they're gone now rather than fixed: the
[Gemini client](#build_gemini_client--build_roboflow_client) moved to a
plain API key with no GCP project tied to it at all, so there's nothing
here left to break the same way.

### `get_cameras()`

```python
def get_cameras():
    url = "https://webcams.nyctmc.org/api/cameras"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching cameras: {e}")
        return []
```

Straightforward GET + JSON parse. `raise_for_status()` turns a bad HTTP
status into an exception, which the `except` immediately catches and turns
into an empty list — so a failed fetch here doesn't crash the app, it just
results in "no cameras," which the caller (`main()` in `main.py`, or
`lifespan()` in `app.py`) checks for. The `timeout=10` was added during
the `app.py` work — its absence was flagged as a real reliability gap in
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md#reliability) (an
unbounded hang here would freeze `app.py`'s startup, not just one
`main.py` run), so it got fixed while this code was already being touched
for the extraction.

### `filter_online_cameras()`

```python
return [c for c in cameras if str(c.get("isOnline")).lower() == "true"]
```

The `str(...).lower() == "true"` dance exists because the API returns
`isOnline` as the **string** `"true"`, not a JSON boolean `true`. A naive
`if c.get("isOnline")` would be truthy for *any* non-empty string,
including the string `"false"` — that bug would silently include every
offline camera too. Confirmed by looking at the raw API response; see
[API_EXAMPLES.md](API_EXAMPLES.md#1-nyc-dot-camera-list--get-httpswebcamsnyctmcorgapicameras).

### `fetch_frame(image_url)`

```python
def fetch_frame(image_url):
    response = requests.get(image_url, timeout=10)
    response.raise_for_status()
    return response.content
```

Pulled out as its own function during the `pipeline.py` extraction (it
used to be two inline lines in `poll_camera`) specifically so `app.py`
could wrap it in `asyncio.to_thread(fetch_frame, image_url)` — see the
`app.py` section below for why that matters.

### `build_gemini_client()` / `build_roboflow_client()`

```python
def build_gemini_client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def build_roboflow_client():
    return InferenceHTTPClient(api_url=ROBOFLOW_API_URL, api_key=os.environ["ROBOFLOW_API_KEY"])
```

New in the extraction — previously this setup was inlined directly in
`poll_camera`. Both entry points need to build these clients exactly once
(not per-frame; construction isn't free) and then reuse them across every
iteration of their respective loops, so giving the construction its own
named function meant `main.py`'s `poll_camera()` and `app.py`'s
`rotation_loop()` could each call the same two lines instead of repeating
Gemini's client setup and Roboflow's client setup independently.

This function has been rewritten **twice**, for two unrelated reasons:

1. **SDK migration** — off the deprecated `vertexai.generative_models`
   SDK (retiring June 24, 2026) onto `google-genai`. It originally called
   `vertexai.init(...)` and returned a `GenerativeModel("gemini-2.5-flash")`;
   after this change it returned a `genai.Client(vertexai=True, ...)`
   that isn't tied to one model name. That shift — from "the client *is*
   a specific model" to "the client is generic, you name the model per
   call" — is why the model string lives in `analyze_frame()` below, not
   here, regardless of which backend the client points at.
2. **Backend switch, Vertex AI → direct Gemini API** — the hackathon GCP
   project this ran against had its account deleted
   (`invalid_grant: Account has been deleted`), and rather than redo the
   full GCP project + billing + IAM setup under a new account, the client
   now points at Google's direct Gemini Developer API instead:
   `genai.Client(api_key=...)` in place of
   `genai.Client(vertexai=True, project=..., location=...)`. Same SDK,
   different backend — see
   [RUNBOOK.md](RUNBOOK.md#setting-up-the-gemini-key) for the full story
   and why this is arguably the better default going forward regardless
   (no GCP project/billing/IAM needed at all). The function name changed
   from `build_vertex_client` to `build_gemini_client` to match — it was
   never really "the Vertex client," it's "the client that talks to
   Gemini," and now the name says so.

### `analyze_frame(client, frame)`

```python
def analyze_frame(client, frame):
    image_part = Part.from_bytes(data=frame, mime_type="image/jpeg")
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[image_part, "Describe the traffic and road conditions visible in this camera image in one concise sentence."],
    )
    return response.text.strip()
```

Takes an already-constructed client (from `build_gemini_client()`, called
once) and raw JPEG bytes. `Part.from_bytes` wraps bytes for a multimodal
prompt; the list `[image_part, "..."]` is "image, then text instruction,"
which is how you mix modalities in a single `generate_content` call.

The model name is `gemini-flash-latest`, not `gemini-2.5-flash` — a
direct consequence of the backend switch above. `gemini-2.5-flash` (used
throughout while this ran on Vertex AI) returned
`404: This model ... is no longer available to new users` against a fresh
direct-API key; `gemini-flash-latest` is an alias Google maintains to
always point at their current recommended flash model, chosen specifically
so this doesn't silently break again the same way.

Only `.text` is used — the response object carries much more (token
counts, finish reason, thinking-token counts). See
[API_EXAMPLES.md](API_EXAMPLES.md#3-vertex-ai--clientmodelsgenerate_content)
for the full shape and why that matters for cost.

No check on `finish_reason` — if Gemini ever returns something other than
`STOP` (e.g. blocked by a safety filter), `.text` may not exist and this
would raise, which both callers catch with a generic `except Exception`.

### `detect_vehicles(roboflow_client, frame)`

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

## `main.py` — local script

### `open_camera_viewer(all_cams, interval)`

The largest function in `main.py` and the only one that doesn't call an
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
fails silently (the page just won't work, no Python-side error). `app.py`'s
`render_viewer_page()` (below) shares this exact same fragility — it's
copy-derived from this function, f-string escaping and all.

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
(`app.py` inherits this same idea but the consequences are worse there —
see that section below.)

**Why Leaflet + OpenStreetMap and not an embedded NYC DOT map:** the real
`webcams.nyctmc.org/map` page sends `X-Frame-Options: DENY`, confirmed by
checking its response headers directly — it cannot be iframed, full stop.
Leaflet + OSM tiles is a free, no-API-key alternative loaded from a CDN
inside the generated page.

**Why a temp file:** `tempfile.mkstemp(suffix=".html")` avoids cluttering
the project directory and guarantees a unique filename per run (so
rotation state from a previous run's leftover file, if any, can never be
opened by mistake — every run gets a fresh file).

### `poll_camera(all_cams, interval=10)`

The orchestration loop. Three things happen once, before the loop starts:
1. `open_camera_viewer(all_cams, interval)` — opens the browser tab.
2. `build_gemini_client()` — one Gemini client, reused every iteration.
3. `build_roboflow_client()` — one Roboflow client, reused every iteration.

(These last two used to be inlined here directly; they now come from
`pipeline.py` — see above.)

Then the loop:
```python
idx = 0
while True:
    cam = all_cams[idx]
    # fetch_frame(), analyze_frame(), detect_vehicles(), print results
    idx = (idx + 1) % len(all_cams)
    time.sleep(interval)
```

One camera is fully processed — fetched, described by Gemini, scanned by
Roboflow, printed — **per `interval` seconds**, not per camera per second.
With ~963 online cameras and a 10s interval, a full pass through every
camera takes roughly `963 × (10s + processing time)` ≈ **2.5–3 hours**.
Whether that cadence is acceptable depends entirely on what the app is
for — see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md#throughput--the-963-camera-problem)
for the scaling implications of that number. (`app.py`'s `rotation_loop()`
has the identical cadence and the identical problem — going Cloud Run
doesn't fix throughput, see that section below.)

Two separate `except` blocks distinguish network failures
(`requests.RequestException`, e.g. the camera's image endpoint timing out)
from everything else (`Exception`, which covers both Gemini and Roboflow
failures) — both just print and move on to the next camera rather than
stopping the loop, since one bad camera shouldn't take down the whole
rotation.

`KeyboardInterrupt` (Ctrl+C) is the only intended way to stop — caught
around the `while True`, printing a clean "Polling stopped." message
instead of a stack trace.

### `main()`

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

## `app.py` — Cloud Run service

Same job as `main.py`, restructured for a request/response server instead
of a script with a display to open a browser on. See
[design/cloud-run-deployment.md](design/cloud-run-deployment.md) for the
design this implements and why this shape was chosen over a Cloud Run
Jobs/batch alternative.

### `rotation_loop()`

```python
async def rotation_loop():
    gemini_client = build_gemini_client()
    roboflow_client = build_roboflow_client()
    idx = 0
    while True:
        cam = all_cameras[idx]
        image_url = cam.get("imageUrl")
        try:
            if image_url:
                frame = await asyncio.to_thread(fetch_frame, image_url)
                description = await asyncio.to_thread(analyze_frame, gemini_client, frame)
                vehicles = await asyncio.to_thread(detect_vehicles, roboflow_client, frame)
                async with state_lock:
                    state["camera"] = {...}
                    state["description"] = description
                    state["vehicles"] = vehicles
                    state["updated_at"] = time.time()
        except Exception:
            logger.exception("cycle failed for %s", cam.get("name"))
        idx = (idx + 1) % len(all_cameras)
        await asyncio.sleep(ROTATE_INTERVAL)
```

This is `poll_camera`'s loop with two real changes, not just a syntax
port:

**`asyncio.to_thread(...)` around every blocking call.** `requests`, the
Vertex AI SDK, and `inference_sdk` are all **synchronous** — none of them
know how to `await`. Calling them directly inside this `async def` would
block the *entire* event loop for the full duration of each call,
including every other request the server is trying to handle at that
moment (like a viewer's `/api/status` poll). `asyncio.to_thread` runs the
blocking call in a worker thread instead, letting the event loop keep
serving other requests while a Gemini or Roboflow call is in flight. This
is the single most important difference between "a loop that happens to
use `async def`" and "a loop that doesn't freeze the server."

**Writing to `state` under `state_lock` instead of printing.** `print()`
has no equivalent concept of "who's reading this" — it just goes to
stdout. Here, multiple things need to read the *current* result
concurrently (any number of `/api/status` requests, from any number of
viewers, at any time), so the result lives in a plain dict guarded by an
`asyncio.Lock`, written once per cycle and read on every poll. The lock
matters even though Python's GIL makes individual dict writes atomic —
without it, a reader could observe a half-updated `state` (e.g., new
`description` but still-old `camera` from four fields being set one at a
time) if a write happened to interleave with a read at just the wrong
`await` point.

Errors here are caught more broadly than `main.py`'s two-`except`
approach — one `except Exception` covers frame-fetch, Gemini, and
Roboflow failures alike, all just logged and skipped. That's a slight
regression in error specificity versus `main.py`, not a deliberate
improvement; it wasn't revisited during the port.

### `lifespan()`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global all_cameras
    cams = get_cameras()
    online = filter_online_cameras(cams)
    if not online:
        logger.error("No online cameras found at startup; rotation loop not started.")
    else:
        all_cameras = online
        asyncio.create_task(rotation_loop())
    yield

app = FastAPI(lifespan=lifespan)
```

FastAPI's modern startup/shutdown hook (the older `@app.on_event("startup")`
decorator still works but is deprecated; `lifespan` is the current
pattern). Everything before `yield` runs once when the server starts —
fetch the camera list, then launch `rotation_loop()` as a background
`asyncio` task so it runs concurrently with the server handling requests,
rather than blocking startup forever (which a plain `await rotation_loop()`
here would do, since that function never returns).

### `render_viewer_page(all_cams, interval)`

Structurally identical to `main.py`'s `open_camera_viewer()` — same
Leaflet/OSM map, same embedded camera JSON, same rotating `<img>` — with
two additions: it **returns** the HTML string instead of writing it to a
file and calling `webbrowser.open()` (there's nowhere to open a browser
*on* inside a Cloud Run container), and it adds an `#analysis` panel with
its own polling script:

```javascript
async function pollStatus() {
    const res = await fetch('/api/status');
    const s = await res.json();
    // ...update #analysis with s.camera.name, s.description, s.vehicles
}
pollStatus();
setInterval(pollStatus, 5000);
```

The analysis panel's copy explicitly says the camera it names **may not
match the image currently pictured above it** — see
[ARCHITECTURE.md](ARCHITECTURE.md#important-design-note-two-independent-rotation-loops)
and the detailed root-cause writeup in
[design/cloud-run-deployment.md](design/cloud-run-deployment.md#known-limitation-found-during-implementation-image-and-analysis-can-point-at-different-cameras)
for why: this page's own image rotation is a client-side `setInterval`
that starts fresh, from index 0, whenever *that specific browser tab*
loads — completely independent of `rotation_loop()`'s single server-side
index. Two people opening the page five minutes apart see different
images at any given instant, and neither is likely to match wherever the
one shared server loop currently is. The UI says so rather than implying
they're in sync.

### `GET /` and `GET /api/status`

```python
@app.get("/", response_class=HTMLResponse)
async def index():
    return render_viewer_page(all_cameras, ROTATE_INTERVAL)

@app.get("/api/status")
async def status():
    async with state_lock:
        return JSONResponse(dict(state))
```

Deliberately thin. `index()` re-renders the page on every request (cheap —
it's string formatting, no I/O) rather than caching it, so a fresh viewer
always gets the current `all_cameras` list even though in practice that
list is only ever set once, at startup. `status()` just snapshots
`state` under the lock and returns it as-is — see
[API_EXAMPLES.md](API_EXAMPLES.md#5-our-own-api--apppy-cloud-run-service)
for a real captured response and what each field means, including the
all-`null` shape before the first rotation cycle completes.
