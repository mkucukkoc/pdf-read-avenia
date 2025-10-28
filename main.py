import logging
import os
import sys
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import create_auth_middleware
from .routes.presentation import router as presentation_router

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s %(levelname)s [%(name)s] %(message)s")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

app = FastAPI(title="Avenia Presentation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(create_auth_middleware())

app.include_router(presentation_router)


@app.get("/health")
async def health_check():
    return {
        "ok": True,
        "service": "presentation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "pdf-read-fresh.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
