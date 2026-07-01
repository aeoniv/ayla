from fastapi import FastAPI

from .routes import admin, auth, feed, movements, payment, playback

app = FastAPI(title="Ayla delivery-service", version="0.1.0")

app.include_router(auth.router)
app.include_router(feed.router)
app.include_router(movements.router)
app.include_router(playback.router)
app.include_router(payment.router)
app.include_router(admin.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "delivery-service"}
