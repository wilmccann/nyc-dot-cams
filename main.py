import os
import requests
import tempfile
import time
import sys
import webbrowser

import cv2
import numpy as np
import vertexai
from dotenv import load_dotenv
from vertexai.generative_models import GenerativeModel, Part
from inference_sdk import InferenceHTTPClient

load_dotenv()

PROJECT_ID = "cloudrun-hack26nyc-4392"
LOCATION = "us-central1"

ROBOFLOW_API_URL = "https://serverless.roboflow.com"
ROBOFLOW_MODEL_ID = "vehicle-detection-3mmwj/1"

def get_cameras():
    """Fetches all cameras from the NYC DOT API."""
    url = "https://webcams.nyctmc.org/api/cameras"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching cameras: {e}")
        return []

def filter_online_cameras(cameras):
    """Filters for cameras that are currently online."""
    return [c for c in cameras if str(c.get("isOnline")).lower() == "true"]

def analyze_frame(model, frame):
    """Sends a frame to Vertex AI Gemini for a one-sentence traffic description."""
    image_part = Part.from_data(frame, mime_type="image/jpeg")
    response = model.generate_content(
        [image_part, "Describe the traffic and road conditions visible in this camera image in one concise sentence."]
    )
    return response.text.strip()

def detect_vehicles(roboflow_client, frame):
    """Runs Roboflow object detection on a frame and summarizes counts by class."""
    image = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
    result = roboflow_client.infer(image, model_id=ROBOFLOW_MODEL_ID)
    predictions = result.get("predictions", [])
    counts = {}
    for pred in predictions:
        counts[pred["class"]] = counts.get(pred["class"], 0) + 1
    if not counts:
        return "no vehicles detected"
    return ", ".join(f"{count} {cls}" for cls, count in sorted(counts.items()))

def open_camera_viewer(cam, image_url, interval):
    """Opens a local HTML page that auto-refreshes the camera image in the browser."""
    html = f"""<!DOCTYPE html>
<html>
<head><title>{cam.get('name')}</title></head>
<body style="margin:0;background:#111;color:#eee;font-family:sans-serif;text-align:center;">
<h2>{cam.get('name')} ({cam.get('area')})</h2>
<img id="cam" src="{image_url}" style="max-width:100%;">
<script>
setInterval(function() {{
    document.getElementById('cam').src = "{image_url}?t=" + Date.now();
}}, {interval * 1000});
</script>
</body>
</html>"""
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w") as f:
        f.write(html)
    webbrowser.open(f"file://{path}")

def poll_camera(cam, interval=10):
    """Polls a specific camera's image URL in a loop."""
    print(f"Polling camera: {cam.get('name')} (ID: {cam.get('id')})")
    print(f"Borough: {cam.get('area')}")
    print("Press Ctrl+C to stop.")

    image_url = cam.get("imageUrl")
    if not image_url:
        print("No image URL available for this camera.")
        return

    open_camera_viewer(cam, image_url, interval)

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.5-flash")

    roboflow_client = InferenceHTTPClient(
        api_url=ROBOFLOW_API_URL,
        api_key=os.environ["ROBOFLOW_API_KEY"],
    )

    try:
        while True:
            try:
                response = requests.get(image_url)
                response.raise_for_status()
                frame = response.content

                description = analyze_frame(model, frame)
                vehicles = detect_vehicles(roboflow_client, frame)
                print(f"[{time.strftime('%H:%M:%S')}] {description} | Detected: {vehicles}")

            except requests.RequestException as e:
                print(f"Error fetching frame: {e}")
            except Exception as e:
                print(f"Error analyzing frame: {e}")

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

    # For now, let's just pick the first online camera or let the user filter.
    # We could implement a simple filter by borough if desired.
    boroughs = sorted(list(set(c.get("area") for c in online if c.get("area"))))
    print(f"Available boroughs: {', '.join(boroughs)}")
    
    # Simple selection logic: first online camera
    cam = online[0]
    poll_camera(cam)

if __name__ == "__main__":
    main()
