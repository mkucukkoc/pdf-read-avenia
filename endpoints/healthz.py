from main import app


@app.get("/healthz")
def healthz():
    return "OK", 200
