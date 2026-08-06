from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv(override=False)

    host = (os.getenv("AIDA_MOBILE_HOST") or "0.0.0.0").strip()
    port = _port_from_environment()

    uvicorn.run(
        "aida.mobile_api.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def _port_from_environment() -> int:
    raw = (os.getenv("AIDA_MOBILE_PORT") or "8765").strip()
    try:
        port = int(raw)
    except ValueError:
        return 8765
    if not 1 <= port <= 65_535:
        return 8765
    return port


if __name__ == "__main__":
    main()
