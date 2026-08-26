# Multi-language base container with Python, Node.js, Go (Golang), and Playwright
FROM python:3.11-slim

# Prevent interactive prompts during apt install
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    PATH="/usr/local/go/bin:${PATH}" \
    NODE_OPTIONS="--max-old-space-size=180"

WORKDIR /app

# Install system dependencies (Node.js 20, ffmpeg, Go 1.23, and Playwright browser libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ffmpeg \
    ca-certificates \
    git \
    build-essential \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libasound2 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && curl -fsSL https://go.dev/dl/go1.23.6.linux-amd64.tar.gz | tar -C /usr/local -xz \
    && rm -rf /var/lib/apt/lists/*

# Copy package dependency manifests
COPY package*.json ./
COPY requirements.txt ./

# Install Node & Python dependencies, yt-dlp standalone binary, and Playwright Chromium
RUN pip install --no-cache-dir -r requirements.txt \
    && curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp \
    && npm install \
    && python -m playwright install chromium

# Copy application files
COPY . .

# Build Go WhatsMeow + MeowCaller WhatsApp service binary
RUN cd YamzzBot-Caller-main \
    && go build -o ../wp_whatsmeow_service . \
    && chmod +x ../wp_whatsmeow_service || true

# Expose default port
EXPOSE 10000

# Start the main master service
CMD ["python", "5.py"]
