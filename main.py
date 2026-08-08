"""Local FastAPI server: camera + map viewer where Gemini/Roboflow are
called on demand — once for a randomly-picked camera on page load, and
once each time you click a different camera on the map — instead of
continuously polling in the background. That old design burned through
the Gemini free-tier daily quota in a few minutes; this one only spends
quota when you actually look at something new.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from pipeline import (
    analyze_frame,
    build_gemini_client,
    build_roboflow_client,
    detect_vehicles,
    fetch_frame,
    filter_online_cameras,
    get_cameras,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nyc-dot-cams")

all_cameras = []
cameras_by_id = {}
gemini_client = None
roboflow_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global all_cameras, cameras_by_id, gemini_client, roboflow_client
    cams = get_cameras()
    online = filter_online_cameras(cams)
    if not online:
        logger.error("No online cameras found at startup.")
    all_cameras = online
    cameras_by_id = {c["id"]: c for c in online}
    gemini_client = build_gemini_client()
    roboflow_client = build_roboflow_client()
    yield


app = FastAPI(lifespan=lifespan)


def render_viewer_page(all_cams):
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
<title>NYC DOT Cameras</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:sans-serif; display:flex; height:100vh; }}
  .pane {{ width:50%; height:100vh; box-sizing:border-box; }}
  #cam-pane {{ text-align:center; overflow:auto; }}
  #map {{ height:100%; cursor:pointer; }}
  #hint {{ color:#fc6; margin-top:8px; }}
  #analysis {{ margin-top:16px; padding:0 16px; text-align:left; color:#9cf; min-height:3em; }}
  #analysis .stale {{ color:#777; font-size:0.85em; }}
</style>
</head>
<body>
<div class="pane" id="cam-pane">
  <h2 id="cam-title"></h2>
  <img id="cam" style="max-width:100%;">
  <div id="hint">Select another camera (from map) &rarr;</div>
  <div id="analysis"></div>
</div>
<div class="pane" id="map"></div>
<script>
const cameras = {json.dumps(markers)};
const camerasById = {{}};
cameras.forEach(function(c) {{ camerasById[c.id] = c; }});

const initial = cameras[Math.floor(Math.random() * cameras.length)];

const map = L.map('map').setView([initial.lat, initial.lon], 12);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

const camImg = document.getElementById('cam');
const camTitle = document.getElementById('cam-title');
const analysisEl = document.getElementById('analysis');
let highlight = null;
let currentId = null;

// Every camera is a clickable marker — clicking one is what triggers a
// Gemini/Roboflow call now, not a timer. Gemini's free-tier daily quota
// is only 20 requests for the current model, so calls only happen when
// you actually pick something to look at.
cameras.forEach(function(c) {{
    L.circleMarker([c.lat, c.lon], {{radius: 4, color: '#3388ff', fillOpacity: 0.6}})
        .addTo(map)
        .bindPopup(c.name)
        .on('click', function() {{ selectCamera(c.id); }});
}});

async function selectCamera(id) {{
    if (id === currentId) return;
    currentId = id;
    const c = camerasById[id];

    camImg.src = c.imageUrl + "?t=" + Date.now();
    camTitle.textContent = c.name + " (" + c.area + ")";

    if (highlight) {{ map.removeLayer(highlight); }}
    highlight = L.circleMarker([c.lat, c.lon], {{radius: 10, color: '#ff3333', fillColor: '#ff3333', fillOpacity: 0.9, weight: 2}})
        .addTo(map)
        .bindPopup(c.name)
        .openPopup();
    map.panTo([c.lat, c.lon]);

    analysisEl.innerHTML = '<span class="stale">Analyzing&hellip;</span>';
    try {{
        const res = await fetch('/api/analyze/' + encodeURIComponent(id));
        const s = await res.json();
        if (s.error) {{
            analysisEl.innerHTML = '<span class="stale">Analysis failed: ' + s.error + '</span>';
            return;
        }}
        // Gemini and Roboflow are reported independently -- one failing
        // (e.g. a Gemini quota hit) still shows the other's result.
        const descLine = s.description
            ? s.description
            : '<span class="stale">Gemini unavailable: ' + s.description_error + '</span>';
        const vehLine = s.vehicles
            ? 'Detected: ' + s.vehicles
            : '<span class="stale">Roboflow unavailable: ' + s.vehicles_error + '</span>';
        analysisEl.innerHTML = descLine + '<br>' + vehLine;
    }} catch (e) {{
        analysisEl.innerHTML = '<span class="stale">Analysis unavailable: ' + e + '</span>';
    }}
}}

selectCamera(initial.id);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return render_viewer_page(all_cameras)


@app.get("/api/analyze/{camera_id}")
async def analyze(camera_id: str):
    cam = cameras_by_id.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Unknown camera id")

    image_url = cam.get("imageUrl")
    if not image_url:
        raise HTTPException(status_code=422, detail="Camera has no image URL")

    try:
        frame = await asyncio.to_thread(fetch_frame, image_url)
    except Exception as e:
        logger.exception("frame fetch failed for %s", cam.get("name"))
        return JSONResponse({"error": str(e)}, status_code=502)

    # Gemini and Roboflow are independent services -- one failing (e.g. a
    # Gemini quota hit) shouldn't hide a result the other successfully
    # produced from the same frame.
    description, description_error = None, None
    try:
        description = await asyncio.to_thread(analyze_frame, gemini_client, frame)
    except Exception as e:
        logger.exception("Gemini analysis failed for %s", cam.get("name"))
        description_error = str(e)

    vehicles, vehicles_error = None, None
    try:
        vehicles = await asyncio.to_thread(detect_vehicles, roboflow_client, frame)
    except Exception as e:
        logger.exception("Roboflow analysis failed for %s", cam.get("name"))
        vehicles_error = str(e)

    logger.info("%s: %s | Detected: %s", cam.get("name"), description or description_error, vehicles or vehicles_error)
    return JSONResponse({
        "camera": {"id": cam["id"], "name": cam.get("name"), "area": cam.get("area")},
        "description": description,
        "description_error": description_error,
        "vehicles": vehicles,
        "vehicles_error": vehicles_error,
    })


if __name__ == "__main__":
    import uvicorn

    # loop="asyncio" instead of the default uvloop (auto-selected since
    # uvicorn[standard] installs it): uvloop doesn't reliably propagate
    # breakpoints into PyCharm's debugger, including inside the
    # asyncio.to_thread() calls in analyze() above. Not needed for
    # performance here -- this is a single-user local tool, not a
    # production server under load.
    uvicorn.run(app, host="0.0.0.0", port=8080, loop="asyncio")
