import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import authoring, score

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Ayla pose-scoring-service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://studio-3654876024-6b075.web.app", "https://ayla-bot.web.app", "https://web.telegram.org"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(authoring.router)
app.include_router(score.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "pose-scoring-service"}
