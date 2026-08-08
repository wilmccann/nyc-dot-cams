# Captured API Examples

These are **real, captured responses** from every external API this project
calls, taken on **2026-08-08** against the camera "Central Park West @ 86 St".
They originally existed because the two paid/gated services this project
used — Vertex AI (via a hackathon GCP project) and Roboflow (via a demo API
key) — were expected to lose access within 24 hours of writing this. That
prediction held: the hackathon account was later deleted
(`invalid_grant: Account has been deleted`), which is part of why Gemini
access no longer goes through Vertex AI at all — see section 3 below and
[RUNBOOK.md](RUNBOOK.md#setting-up-the-gemini-key). The NYC DOT API is
public and permanent, but its response is included too for completeness and
because the exact frame shown here is what produced the Gemini and
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

## 3. Gemini — `client.models.generate_content()`

This is the SDK call in `analyze_frame()`; under the hood it's a POST to:
```
https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent
```
(Not Vertex AI — this project switched backends; see
[RUNBOOK.md](RUNBOOK.md#setting-up-the-gemini-key) for why. Same
`google-genai` SDK, same `client.models.generate_content()` call shape,
different `client` construction and a different underlying endpoint.)

**Input:** the JPEG bytes above (as a `Part.from_bytes(data=..., mime_type="image/jpeg")`)
plus the prompt string `"Describe the traffic and road conditions visible
in this camera image in one concise sentence."`

**Output** (`response.text`):
```
Traffic is light on a multi-lane city street under clear, dry conditions with well-marked lanes and crosswalks.
```

**Full response object**, captured 2026-08-08 via the direct Gemini API
(the same call, run against the earlier Vertex AI backend, is preserved
below for comparison — the shape is nearly identical, the backend swap
changed the client, not how results are read):
```python
GenerateContentResponse(
  automatic_function_calling_history=[],
  candidates=[
    Candidate(
      content=Content(
        parts=[
          Part(
            text='Traffic is light on a multi-lane city street under clear, dry conditions with well-marked lanes and crosswalks.',
            thought_signature=b'...'   # opaque, truncated here; not something the code reads
          ),
        ],
        role='model'
      ),
      finish_reason=<FinishReason.STOP: 'STOP'>,
      index=0
    ),
  ],
  model_version='gemini-3.6-flash',
  response_id='_0J3aoeOC_PI-8YP88ry8QE',
  sdk_http_response=HttpResponse(headers=<dict len=12>),
  usage_metadata=GenerateContentResponseUsageMetadata(
    candidates_token_count=25,
    prompt_token_count=1097,
    prompt_tokens_details=[
      ModalityTokenCount(modality=<MediaModality.IMAGE: 'IMAGE'>, token_count=1080),
      ModalityTokenCount(modality=<MediaModality.TEXT: 'TEXT'>, token_count=17),
    ],
    thoughts_token_count=178,
    total_token_count=1300
  )
)
```

Things worth noticing here that aren't visible from just calling
`.text.strip()` in the code:
- **`model_version='gemini-3.6-flash'`** — the code requests
  `gemini-flash-latest`, an alias; Google is currently resolving it to
  Gemini 3.6 Flash, a newer generation than the `gemini-2.5-flash` this
  project originally pinned. This is exactly the intended behavior (see
  [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md#build_gemini_client--build_roboflow_client))
  — it also means the *actual model answering* can change without any
  code change here, which is a real tradeoff to be aware of, not just a
  convenience.
- **`thoughts_token_count=178`** — still a "thinking" model, still
  billing for reasoning never seen by this code (see
  [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md#cost-the-thinking-token-problem)),
  but notably lower than the ~670–740 range seen on `gemini-2.5-flash` for
  a similar prompt (below) — cost-per-call isn't fixed even for "the same
  code," since the resolved model changes over time.
- **`prompt_tokens_details` image cost jumped**: 1080 tokens for the image
  here vs. 258 on the old Vertex AI capture below, for a similarly-sized
  JPEG. Different model generations appear to tokenize images very
  differently — another reason the cost estimate in
  [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md#cost-the-thinking-token-problem)
  is explicitly a rough, point-in-time estimate, not a guarantee.
- **`finish_reason=STOP`** is the "normal, complete answer" case. Other
  values (`MAX_TOKENS`, `SAFETY`, etc.) would mean the response was cut off
  or blocked — the current code doesn't check this field at all, it just
  trusts `.text` exists.
- No `avg_logprobs` or `create_time` in this capture (both present in the
  Vertex AI capture below) — minor field differences between backends/SDK
  versions that don't affect anything `analyze_frame()` actually reads.

<details>
<summary>Earlier capture against Vertex AI (before the backend switch), for comparison</summary>

```python
GenerateContentResponse(
  automatic_function_calling_history=[],
  candidates=[
    Candidate(
      avg_logprobs=-19.69898165189303,
      content=Content(
        parts=[
          Part(text='Sparse evening traffic is navigating wet, reflective roads under artificial light.'),
        ],
        role='model'
      ),
      finish_reason=<FinishReason.STOP: 'STOP'>
    ),
  ],
  create_time=datetime.datetime(2026, 8, 8, 1, 59, 51, 294969, tzinfo=TzInfo(0)),
  model_version='gemini-2.5-flash',
  response_id='l412armAEq_x88AP7LSy2AQ',
  sdk_http_response=HttpResponse(headers=<dict len=10>),
  usage_metadata=GenerateContentResponseUsageMetadata(
    candidates_token_count=13,
    candidates_tokens_details=[ModalityTokenCount(modality=<MediaModality.TEXT: 'TEXT'>, token_count=13)],
    prompt_token_count=274,
    prompt_tokens_details=[
      ModalityTokenCount(modality=<MediaModality.TEXT: 'TEXT'>, token_count=16),
      ModalityTokenCount(modality=<MediaModality.IMAGE: 'IMAGE'>, token_count=258),
    ],
    thoughts_token_count=672,
    total_token_count=959,
    traffic_type=<TrafficType.ON_DEMAND: 'ON_DEMAND'>
  )
)
```
Endpoint at the time: `https://us-central1-aiplatform.googleapis.com/v1beta1/projects/cloudrun-hack26nyc-4392/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent`,
via `genai.Client(vertexai=True, project=..., location=...)`.
</details>

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
