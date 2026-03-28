FROM python:3.11-slim

# Install ffmpeg (required by Whisper)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model at build time so it's baked into the image
# Change "small" to "medium" if you need more accuracy
ARG WHISPER_MODEL=small
RUN python -c "import whisper; whisper.load_model('${WHISPER_MODEL}')"

COPY . .

CMD ["python", "bot.py"]