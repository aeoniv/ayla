from fastapi import FastAPI

from .routes import coach

app = FastAPI(title="Ayla coaching-agent-service", version="0.1.0")

app.include_router(coach.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "coaching-agent-service"}
