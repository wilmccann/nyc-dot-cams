"""Cloud Run service: same rotating camera + map viewer as main.py, but the
Gemini/Roboflow analysis runs server-side (it needs credentials the browser
can never hold) while images and the map stay entirely client-side, exactly
as they do in the local version. See docs/design/cloud-run-deployment.md
for the design this implements.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from pipeline import (
    analyze_frame,
    build_roboflow_client,
    build_vertex_model,
    detect_vehicles,
    fetch_frame,
    filter_online_cameras,
    get_cameras,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nyc-dot-cams")

ROTATE_INTERVAL = 10

all_cameras = []
state = {"camera": None, "description": None, "vehicles": None, "updated_at": None}
state_lock = asyncio.Lock()


async def rotation_loop():
    model = build_vertex_model()
    roboflow_client = build_roboflow_client()

    idx = 0
    while True:
        cam = all_cameras[idx]
        image_url = cam.get("imageUrl")
        try:
            if image_url:
                frame = await asyncio.to_thread(fetch_frame, image_url)
                description = await asyncio.to_thread(analyze_frame, model, frame)
                vehicles = await asyncio.to_thread(detect_vehicles, roboflow_client, frame)

                async with state_lock:
                    state["camera"] = {"id": cam.get("id"), "name": cam.get("name"), "area": cam.get("area")}
                    state["description"] = description
                    state["vehicles"] = vehicles
                    state["updated_at"] = time.time()

                logger.info("%s: %s | Detected: %s", cam.get("name"), description, vehicles)
        except Exception:
            logger.exception("cycle failed for %s", cam.get("name"))

        idx = (idx + 1) % len(all_cameras)
        await asyncio.sleep(ROTATE_INTERVAL)


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


def render_viewer_page(all_cams, interval):
    markers = [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "area": c.get("area"),
            "lat": c.get("latitude"),
            "lon": c.get("longitude"),
            "imageUrl": c.get("imageUrl"),
        }
        for c in all_cams
        if c.get("latitude") is not None and c.get("longitude") is not None and c.get("imageUrl")
    ]

    return f"""<!DOCTYPE html>
<html>
<head>
<title>NYC DOT Camera Rotation</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:sans-serif; display:flex; height:100vh; }}
  .pane {{ width:50%; height:100vh; box-sizing:border-box; }}
  #cam-pane {{ text-align:center; overflow:auto; }}
  #map {{ height:100%; }}
  #analysis {{ margin-top:16px; padding:0 16px; text-align:left; color:#9cf; min-height:3em; }}
  #analysis .stale {{ color:#777; font-size:0.85em; }}
  #analysis .analysis-cam {{ color:#fc6; }}
</style>
</head>
<body>
<div class="pane" id="cam-pane">
  <h2 id="cam-title"></h2>
  <img id="cam" style="max-width:100%;">
  <div id="analysis">Waiting for first analysis cycle&hellip;</div>
</div>
<div class="pane" id="map"></div>
<script>
const cameras = {json.dumps(markers)};
const rotateMs = {interval * 1000};

const map = L.map('map').setView([cameras[0].lat, cameras[0].lon], 12);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

cameras.forEach(function(c) {{
    L.circleMarker([c.lat, c.lon], {{radius: 4, color: '#3388ff', fillOpacity: 0.6}})
        .addTo(map)
        .bindPopup(c.name);
}});

const camImg = document.getElementById('cam');
const camTitle = document.getElementById('cam-title');
const analysisEl = document.getElementById('analysis');
let highlight = null;

function showCamera(i) {{
    const c = cameras[i];
    camImg.src = c.imageUrl + "?t=" + Date.now();
    camTitle.textContent = c.name + " (" + c.area + ")";
    if (highlight) {{ map.removeLayer(highlight); }}
    highlight = L.circleMarker([c.lat, c.lon], {{radius: 10, color: '#ff3333', fillColor: '#ff3333', fillOpacity: 0.9, weight: 2}})
        .addTo(map)
        .bindPopup(c.name)
        .openPopup();
    map.panTo([c.lat, c.lon]);
}}

let idx = 0;
showCamera(idx);
setInterval(function() {{
    idx = (idx + 1) % cameras.length;
    showCamera(idx);
}}, rotateMs);

// Analysis text comes from the server, which is the only thing that holds
// Vertex AI / Roboflow credentials — images and the map above never touch it.
//
// Important: the server runs ONE shared rotation loop for all viewers,
// independent of each browser tab's own image-rotation timer above. This
// analysis is very likely describing a DIFFERENT camera than the one
// currently pictured, not just a delayed version of it — so the camera
// name is shown explicitly here rather than implying they match.
async function pollStatus() {{
    try {{
        const res = await fetch('/api/status');
        const s = await res.json();
        if (!s.camera) {{
            analysisEl.innerHTML = '<span class="stale">Waiting for first server analysis cycle&hellip;</span>';
            return;
        }}
        const ageSec = Math.round(Date.now() / 1000 - s.updated_at);
        analysisEl.innerHTML =
            '<span class="stale">Server analysis (independent rotation, may be a different camera than pictured above):</span><br>' +
            '<span class="analysis-cam">' + s.camera.name + '</span> &mdash; ' + s.description + '<br>' +
            'Detected: ' + s.vehicles +
            '<br><span class="stale">as of ' + ageSec + 's ago</span>';
    }} catch (e) {{
        analysisEl.innerHTML = '<span class="stale">Analysis unavailable: ' + e + '</span>';
    }}
}}
pollStatus();
setInterval(pollStatus, 5000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return render_viewer_page(all_cameras, ROTATE_INTERVAL)


@app.get("/api/status")
async def status():
    async with state_lock:
        return JSONResponse(dict(state))
