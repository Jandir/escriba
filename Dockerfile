FROM python:3.13-slim

# Install ffmpeg for yt-dlp and other dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
# Note: .dockerignore will handle excluding unnecessary files
COPY . .

# Set entrypoint to escriba.py
ENTRYPOINT ["python", "escriba.py"]
