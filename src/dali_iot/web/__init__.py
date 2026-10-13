"""The web UI: a FastAPI JSON API over the site file and the gateway, plus the built SPA.

``create_app`` is the whole surface; ``dali-iot serve`` runs it under uvicorn.
Needs the ``web`` extra (``uv sync --extra web``).
"""
