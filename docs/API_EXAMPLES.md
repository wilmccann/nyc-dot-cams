# Captured API Examples

These are **real, captured responses** from every external API this project
calls, taken on **2026-08-08** against the camera "Central Park West @ 86 St".
They exist because the two paid/gated services this project uses — Vertex AI
(via a hackathon GCP project) and Roboflow (via a demo API key) — were
expected to lose access within 24 hours of writing this. The NYC DOT API is
public and permanent, but its response is included too for completeness and
because the exact frame shown here is what produced the Vertex AI and
Roboflow examples below (same camera, same moment).

If you no longer have working credentials, this doc is the way to still
understand exactly what shape of data flows through `pipeline.py` (shared
by both entry points, `main.py` and the Cloud Run service `app.py`) — read
it alongside [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md), which explains
what the code *does* with each of these shapes. Section 5 below also
documents the API this project now *exposes itself*, once deployed as a
Cloud Run service.

## 1. NYC DOT Camera List — `GET https://webcams.nyctmc.org/api/cameras`

No auth required. Called once at startup by `get_cameras()` in
`pipeline.py`. Returns an
array of ~968 objects; one shown here:

```json
{
  "id": "8a6bc417-4877-4ebe-8052-88c1b261baf1",
  "name": "Central Park West @ 86 St",
  "latitude": 40.785302,
  "longitude": -73.969353,
  "area": "Manhattan",
  "isOnline": "true",
  "imageUrl": "https://webcams.nyctmc.org/api/cameras/8a6bc417-4877-4ebe-8052-88c1b261baf1/image"
}
```

Notes:
- `isOnline` is a **string** `"true"`/`"false"`, not a boolean — that's why
  `filter_online_cameras()` does `str(c.get("isOnline")).lower() == "true"`
  instead of a direct truthiness check.
- `imageUrl` is a stable per-camera endpoint that always returns *whatever
  frame is current* — it's not a static image, so re-fetching it later
  returns something different. This is what makes polling meaningful.

## 2. NYC DOT Camera Image — `GET {imageUrl}`

Returns a raw JPEG. The one captured for this doc was 18,737 bytes,
352×240px. No JSON wrapper, no headers of note — just image bytes, which
is why `main.py` passes `response.content` directly around rather than
parsing anything.

## 3. Vertex AI — `GenerativeModel.generate_content()`

This is the SDK call in `analyze_frame()`; under the hood it's a POST to:
```
https://us-central1-aiplatform.googleapis.com/v1/projects/cloudrun-hack26nyc-4392/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent
```

**Input:** the JPEG bytes above (as a `Part`) plus the prompt string
`"Describe the traffic and road conditions visible in this camera image in
one concise sentence."`

**Output** (`response.text`):
```
Moderate nighttime traffic is visible on a wet, reflective road.
```

**Full response object** (what `response.text` is extracted from — the SDK
exposes much more than the text):
```
candidates {
  content {
    role: "model"
    parts {
      text: "Moderate nighttime traffic is visible on a wet, reflective road."
    }
  }
  finish_reason: STOP
  avg_logprobs: -20.939376831054688
}
usage_metadata {
  prompt_token_count: 274
  candidates_token_count: 12
  total_token_count: 1026
  prompt_tokens_details {
    modality: IMAGE
    token_count: 258
  }
  prompt_tokens_details {
    modality: TEXT
    token_count: 16
  }
  candidates_tokens_details {
    modality: TEXT
    token_count: 12
  }
  thoughts_token_count: 740
}
model_version: "gemini-2.5-flash"
create_time {
  seconds: 1786148512
  nanos: 900321000
}
response_id: "oHZ2auH5NrKy88APudnu2Qc"
```

Things worth noticing here that aren't visible from just calling
`.text.strip()` in the code:
- **`thoughts_token_count: 740`** — Gemini 2.5 Flash is a "thinking" model;
  it spent 740 tokens reasoning internally before writing the 12-token
  answer. That reasoning is billed (see `total_token_count: 1026`, which is
  far larger than `prompt_token_count + candidates_token_count` alone)
  even though this code never sees or prints it. This matters for cost —
  see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
- **`prompt_tokens_details`** shows the image itself cost 258 tokens —
  images aren't free just because you're not sending text.
- **`finish_reason: STOP`** is the "normal, complete answer" case. Other
  values (`MAX_TOKENS`, `SAFETY`, etc.) would mean the response was cut off
  or blocked — the current code doesn't check this field at all, it just
  trusts `.text` exists.

## 4. Roboflow — `InferenceHTTPClient.infer()`

Under the hood, a POST to:
```
https://serverless.roboflow.com/vehicle-detection-3mmwj/1
```

**Input:** the same JPEG, decoded to a numpy array via
`cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)`
(the SDK rejects raw JPEG bytes — see the troubleshooting log in
[RUNBOOK.md](RUNBOOK.md#troubleshooting)).

**Full response:**
```json
{
  "inference_id": "98b9fe2d-8268-45e5-884e-8aad74e3959d",
  "time": 0.006098391022533178,
  "image": {
    "width": 352,
    "height": 240
  },
  "predictions": [
    {
      "x": 182.5,
      "y": 117.5,
      "width": 19.0,
      "height": 21.0,
      "confidence": 0.6151835918426514,
      "class": "vehicle",
      "class_id": 0,
      "detection_id": "c2665430-ff32-4371-b5ad-e4f3a86611e1"
    }
  ]
}
```

Notes:
- `x`/`y` are the **center point** of the bounding box in pixels, not the
  top-left corner; `width`/`height` are the box dimensions. `detect_vehicles()`
  in `main.py` doesn't use these coordinates at all right now — it only
  reads `class` to build a count summary (`"1 vehicle"`). The position data
  is there if a future feature wants to draw boxes on the image.
- `class` here is the single generic label `"vehicle"` — this particular
  public model (`vehicle-detection-3mmwj/1`) doesn't distinguish car vs.
  truck vs. bus. A different model would return different class names; the
  code doesn't assume any specific set, it just groups by whatever string
  comes back.
- `time: 0.0061` is **inference time in seconds**, server-side only — it
  doesn't include network latency to reach `serverless.roboflow.com`.
- Only one detection at 0.615 confidence — the model has no built-in
  confidence threshold applied here; every prediction Roboflow returns gets
  counted, however low-confidence.

## 5. Our own API — `app.py` (Cloud Run service)

Deploying the design in
[design/cloud-run-deployment.md](design/cloud-run-deployment.md) means this
project now exposes two endpoints of its own, not just consumes external
ones. Captured from the actual verification deployment on Cloud Run
(2026-08-08), while it was briefly made public for direct browser testing.

### `GET /`

Returns the full viewer page (HTML/CSS/JS) as a string — same content
`main.py`'s `open_camera_viewer()` writes to a temp file locally, but
served over HTTP instead. No parameters, no auth-relevant content in the
body (the embedded camera list is the same public NYC DOT data as section
1 above, just pre-fetched server-side at startup instead of client-side
per request).

### `GET /api/status`

Polled by the page's own JS every 5 seconds (see
`pollStatus()` in `app.py`) to update the analysis panel. Real captured
response:

```json
{
  "camera": {
    "id": "8ccc0c64-65a5-42f9-9eba-cf7aa4a51b09",
    "name": "Belt Pkwy @ Cross Island Split",
    "area": "Queens"
  },
  "description": "Light to moderate nighttime traffic is visible on wet roads.",
  "vehicles": "no vehicles detected",
  "updated_at": 1786152644.90213
}
```

Before the background rotation loop has completed its first cycle (e.g.
immediately after a cold start), every field except `updated_at` is
`null`:
```json
{"camera": null, "description": null, "vehicles": null, "updated_at": null}
```
The client's `pollStatus()` checks for `s.camera` being falsy to show a
"waiting for first analysis cycle" message in that case, rather than
trying to render `null` fields.

Notes:
- This is a deliberately thin wrapper around the `state` dict
  `rotation_loop()` maintains in memory — there's no database, no request
  parameters, no pagination. It reflects whatever camera the server's
  single shared rotation loop most recently finished analyzing, which is
  **not necessarily the camera currently pictured in the page's image
  pane** — see the detailed writeup of why in
  [design/cloud-run-deployment.md](design/cloud-run-deployment.md#known-limitation-found-during-implementation-image-and-analysis-can-point-at-different-cameras).
- `updated_at` is a Unix timestamp (`time.time()`), not ISO 8601 — the
  client computes age in seconds as `Date.now()/1000 - s.updated_at`
  rather than parsing a datetime string.
- No caching headers, no ETag — every poll does a fresh in-memory dict
  read (cheap) but there's nothing here to prevent a client from polling
  far more often than 5s if it wanted to; nothing rate-limits `/api/status`
  itself (see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)).
