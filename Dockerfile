FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libfribidi0 \
    libharfbuzz0b \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "from PIL import features; print('RAQM active:', features.check('raqm'))"

COPY . .

EXPOSE 10000

CMD ["python", "app.py"]
