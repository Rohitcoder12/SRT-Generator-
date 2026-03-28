FROM python:3.11-slim

# Install ffmpeg + clean up in single layer to minimize image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# No cache = smaller image (~300 MB saved)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ✅ Model downloads at runtime into /tmp (NOT baked into image)
# This keeps image well under Railway's 4 GB limit
CMD ["python", "bot.py"]