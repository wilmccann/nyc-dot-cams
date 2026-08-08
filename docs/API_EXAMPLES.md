# Captured API Examples

Real captured responses from the external APIs this project calls that
haven't changed shape across the various rewrites this project has been
through. (Gemini and the app's own endpoints aren't documented here
anymore — they've already drifted stale twice as the code evolved; read
`pipeline.py`/`main.py` directly for those instead of a prose snapshot
that needs manual upkeep.)

## 1. NYC DOT Camera List — `GET https://webcams.nyctmc.org/api/cameras`

No auth required. Called once at startup by `get_cameras()` in
`pipeline.py`. Returns an array of ~968 objects; one shown here:

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
  returns something different.

## 2. NYC DOT Camera Image — `GET {imageUrl}`

Returns a raw JPEG. The one captured for this doc was 18,737 bytes,
352×240px. No JSON wrapper, no headers of note — just image bytes, which
is why `fetch_frame()` in `pipeline.py` returns `response.content`
directly rather than parsing anything.

## 3. Roboflow — `InferenceHTTPClient.infer()`

Under the hood, a POST to:
```
https://serverless.roboflow.com/vehicle-detection-3mmwj/1
```

**Input:** the same JPEG, decoded to a numpy array via
`cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)` —
the SDK rejects raw JPEG bytes despite what its docs suggest.

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
  top-left corner; `width`/`height` are the box dimensions.
  `detect_vehicles()` in `pipeline.py` doesn't use these coordinates at
  all right now — it only reads `class` to build a count summary
  (`"1 vehicle"`). The position data is there if a future feature wants
  to draw boxes on the image.
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
