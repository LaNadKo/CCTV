FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY processor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY processor/ ./processor/
COPY cctv_ai/ ./cctv_ai/

CMD ["python", "-m", "processor.cli", "run"]
