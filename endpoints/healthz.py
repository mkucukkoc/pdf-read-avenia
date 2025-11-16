import logging

from main import app

logger = logging.getLogger("pdf_read_refresh.endpoints.healthz")


@app.get("/healthz")
def healthz():
    logger.info("Health check requested")
    return "OK", 200
