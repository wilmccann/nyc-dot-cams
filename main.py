import json
import tempfile
import time
import webbrowser

import requests
from dotenv import load_dotenv

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

def open_camera_viewer(all_cams, interval):
    """Opens a local HTML page that rotates through all_cams every interval seconds,
    showing each camera's live image and highlighting its position on a map."""
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

    html = f"""<!DOCTYPE html>
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
</style>
</head>
<body>
<div class="pane" id="cam-pane">
  <h2 id="cam-title"></h2>
  <img id="cam" style="max-width:100%;">
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
</script>
</body>
</html>"""
    fd, path = tempfile.mkstemp(suffix=".html")
    with open(path, "w") as f:
        f.write(html)
    webbrowser.open(f"file://{path}")

def poll_camera(all_cams, interval=10):
    """Rotates through all_cams, analyzing one camera's frame every interval seconds."""
    print(f"Rotating through {len(all_cams)} online cameras every {interval}s.")
    print("Press Ctrl+C to stop.")

    open_camera_viewer(all_cams, interval)

    gemini_client = build_gemini_client()
    roboflow_client = build_roboflow_client()

    idx = 0
    try:
        while True:
            cam = all_cams[idx]
            image_url = cam.get("imageUrl")
            try:
                if image_url:
                    frame = fetch_frame(image_url)

                    description = analyze_frame(gemini_client, frame)
                    vehicles = detect_vehicles(roboflow_client, frame)
                    print(f"[{time.strftime('%H:%M:%S')}] {cam.get('name')}: {description} | Detected: {vehicles}")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] {cam.get('name')}: no image URL available.")

            except requests.RequestException as e:
                print(f"Error fetching frame for {cam.get('name')}: {e}")
            except Exception as e:
                print(f"Error analyzing frame for {cam.get('name')}: {e}")

            idx = (idx + 1) % len(all_cams)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nPolling stopped.")

def main():
    print("Fetching NYC DOT cameras...")
    cams = get_cameras()

    online = filter_online_cameras(cams)
    print(f"Found {len(cams)} total cameras, {len(online)} online.")

    if not online:
        print("No online cameras found.")
        return

    boroughs = sorted(list(set(c.get("area") for c in online if c.get("area"))))
    print(f"Available boroughs: {', '.join(boroughs)}")

    poll_camera(online)

if __name__ == "__main__":
    main()
