# Production image for Komuzik — no dev tools, non-root, pinned font checksum.
FROM python:3.11-slim

WORKDIR /app

ARG NERD_FONT_VERSION=v3.4.0
# sha256 of JetBrainsMono.zip from the ryanoasis/nerd-fonts release above
ARG NERD_FONT_SHA256=76f05ff3ace48a464a6ca57977998784ff7bdbb65a6d915d7e401cd3927c493c

# System deps for yt-dlp / ffmpeg / Telethon / stats fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    wget \
    unzip \
    ca-certificates \
    fontconfig \
    fonts-dejavu-core \
    && mkdir -p /usr/local/share/fonts/nerd \
    && wget -qO /tmp/JetBrainsMono.zip \
      "https://github.com/ryanoasis/nerd-fonts/releases/download/${NERD_FONT_VERSION}/JetBrainsMono.zip" \
    && echo "${NERD_FONT_SHA256}  /tmp/JetBrainsMono.zip" | sha256sum -c - \
    && unzip -j /tmp/JetBrainsMono.zip \
      "JetBrainsMonoNerdFont-Regular.ttf" \
      "JetBrainsMonoNerdFont-Bold.ttf" \
      -d /usr/local/share/fonts/nerd \
    && fc-cache -f \
    && rm -f /tmp/JetBrainsMono.zip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

# Production deps only — pytest/ruff/ty stay out of the image
RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY config.yaml .
COPY messages.yaml .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh \
    && mkdir -p /app/session /app/data /tmp/komuzik \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin komuzik \
    && chown -R komuzik:komuzik /app /tmp/komuzik

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HOME=/home/komuzik \
    TMPDIR=/tmp/komuzik \
    UV_CACHE_DIR=/tmp/komuzik/uv-cache

USER komuzik

ENTRYPOINT ["./entrypoint.sh"]
