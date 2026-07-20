# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for yt-dlp, ffmpeg, Telethon, and stats fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    unzip \
    ca-certificates \
    fontconfig \
    fonts-dejavu-core \
    && mkdir -p /usr/local/share/fonts/nerd \
    && wget -qO /tmp/JetBrainsMono.zip \
      https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/JetBrainsMono.zip \
    && unzip -j /tmp/JetBrainsMono.zip \
      "JetBrainsMonoNerdFont-Regular.ttf" \
      "JetBrainsMonoNerdFont-Bold.ttf" \
      -d /usr/local/share/fonts/nerd \
    && fc-cache -f \
    && rm -f /tmp/JetBrainsMono.zip \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen

# Copy application code
COPY src/ ./src/
COPY config.yaml .

# Copy entrypoint script
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create session directory
RUN mkdir -p /app/session

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Run entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
