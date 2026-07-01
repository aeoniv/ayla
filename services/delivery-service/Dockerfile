FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8080

# ffprobe (ffmpeg) is used to enforce the teaser <=12s rule in authoring.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Cloud Run provides $PORT.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
