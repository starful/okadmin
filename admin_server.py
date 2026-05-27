"""Work Hub / OK Admin entry point."""
from __future__ import annotations

import os

from app_factory import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8090)),
        threaded=True,
    )
