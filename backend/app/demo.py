"""Demo entry point: ``uvicorn app.demo:app``.

Same gateway, with demo sign-in enabled and the recorded supplier data, so
every recording take behaves the same (frontend.md §9, B6). Environment
variables still win, e.g. ``UPSTREAM_MODE=live`` for the real API.
"""

import os

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("UPSTREAM_MODE", "fixture")

from app.main import app  # noqa: E402,F401
