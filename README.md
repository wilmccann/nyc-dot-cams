# NYC DOT Camera Pipeline

A minimal pipeline to fetch and poll NYC DOT camera images for real-time processing.

## Setup

This project uses `uv` for dependency management.

1.  Install dependencies:
    ```bash
    uv sync
    ```

## Usage

Run the main script to start polling the first available online camera:

```bash
uv run main.py
```

## Next Steps

- [ ] Add CLI arguments for filtering by borough or camera name.
- [ ] Integrate Roboflow inference.
- [ ] Save frames locally or stream to a visualization tool.
- [ ] Implement multi-camera polling.
