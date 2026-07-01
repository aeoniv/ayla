FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8080

# Native libs required by opencv-python-headless / mediapipe.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
