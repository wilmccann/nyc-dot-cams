import requests
import time
import sys

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

def poll_camera(cam, interval=2):
    """Polls a specific camera's image URL in a loop."""
    print(f"Polling camera: {cam.get('name')} (ID: {cam.get('id')})")
    print(f"Borough: {cam.get('area')}")
    print("Press Ctrl+C to stop.")
    
    image_url = cam.get("imageUrl")
    if not image_url:
        print("No image URL available for this camera.")
        return

    try:
        while True:
            try:
                response = requests.get(image_url)
                response.raise_for_status()
                frame = response.content
                
                # Placeholder for Roboflow or other inference
                print(f"[{time.strftime('%H:%M:%S')}] Frame captured ({len(frame)} bytes)")
                
                # If you were using Roboflow, you'd call it here:
                # results = roboflow_model.predict(frame)
                
            except requests.RequestException as e:
                print(f"Error fetching frame: {e}")
            
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
