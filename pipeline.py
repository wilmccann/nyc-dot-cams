"""Shared camera-fetching and AI-analysis logic.

Used by both main.py (local browser demo) and app.py (Cloud Run service) so
the two entry points don't duplicate the NYC DOT / Vertex AI / Roboflow
client code. See docs/CODE_WALKTHROUGH.md for the reasoning behind these
functions.
"""

import os

import cv2
import numpy as np
import requests
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from inference_sdk import InferenceHTTPClient

PROJECT_ID = "cloudrun-hack26nyc-4392"
LOCATION = "us-central1"

ROBOFLOW_API_URL = "https://serverless.roboflow.com"
ROBOFLOW_MODEL_ID = "vehicle-detection-3mmwj/1"


def get_cameras():
    """Fetches all cameras from the NYC DOT API."""
    url = "https://webcams.nyctmc.org/api/cameras"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching cameras: {e}")
        return []


def filter_online_cameras(cameras):
    """Filters for cameras that are currently online."""
    return [c for c in cameras if str(c.get("isOnline")).lower() == "true"]


def fetch_frame(image_url):
    """Fetches the current JPEG frame for one camera."""
    response = requests.get(image_url, timeout=10)
    response.raise_for_status()
    return response.content


def build_vertex_model():
    """Initializes Vertex AI and returns a Gemini model client."""
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    return GenerativeModel("gemini-2.5-flash")


def build_roboflow_client():
    """Builds a Roboflow hosted-inference client from ROBOFLOW_API_KEY."""
    return InferenceHTTPClient(
        api_url=ROBOFLOW_API_URL,
        api_key=os.environ["ROBOFLOW_API_KEY"],
    )


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
