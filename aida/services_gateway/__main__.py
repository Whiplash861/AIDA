from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = (os.getenv("AIDA_SERVICES_GATEWAY_HOST") or "127.0.0.1").strip()
    port = int((os.getenv("AIDA_SERVICES_GATEWAY_PORT") or "8787").strip())
    uvicorn.run(
        "aida.services_gateway.app:app",
        host=host,
        port=port,
        reload=False,
        limit_concurrency=32,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=35,
    )


if __name__ == "__main__":
    main()
