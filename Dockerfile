FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless apktool zipalign apksigner \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn
COPY . .

CMD gunicorn -b 0.0.0.0:${PORT:-5000} --timeout 180 server:app
