#!/usr/bin/env python3
"""Container entrypoint shim for the testable application runtime."""

from __future__ import annotations

import sys


if "/app/backend" not in sys.path:
    sys.path.insert(0, "/app/backend")

from app.runtime import main  # noqa: E402


raise SystemExit(main())

