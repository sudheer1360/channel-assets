# channel-assets

Public video files and the renderer for my faceless dev channel (Instagram Reels, YouTube Shorts).

- `videos/` finished videos. Metricool reads them from the raw GitHub link.
- `specs/` one JSON spec per video (scenes, on-screen text, voice lines).
- `render.py` turns a spec into a vertical video with an AI voice: `python3 render.py specs/x.json videos/x.mp4`
- `log.md` what has been made and scheduled.

## Veto window
Every video is scheduled at least 12 hours before it goes live. To cancel one, delete it in the Metricool planner.
