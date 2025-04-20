# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies required by yt-dlp and ffmpeg (for audio conversion)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Install poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy only necessary files for dependency installation
COPY pyproject.toml poetry.lock* ./

# Install project dependencies
# --no-root: Don't install the project package itself yet
# Убедимся, что зависимости устанавливаются после копирования lock файла
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi

# Copy the rest of the application code
COPY src/ /app/src/

# Add src directory to PYTHONPATH so python -m can find the package
ENV PYTHONPATH=/app/src

# Copy .env file (optional, but good practice to keep it out of the image if possible)
# You might want to mount this as a volume or use Docker secrets instead
# COPY .env .env

# Command to run the application as a module
# This ensures correct package context for relative imports
CMD ["python", "-m", "komuzik.main"]
