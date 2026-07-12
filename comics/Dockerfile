FROM python:3.12-slim

# gcc/g++/pkg-config/libicu-dev: build PyICU (comictagger dep on linux)
# unar: extract CBR/RAR archives for CBZ conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ pkg-config libicu-dev unar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY comicsbot ./comicsbot

# /data: bot session + state, /inbox: downloads (shared with JDownloader),
# /library: the comics library that Komga/Codex/Mylar read.
ENV HOME=/data DATA_DIR=/data INBOX_DIR=/inbox LIBRARY_DIR=/library
VOLUME ["/data", "/inbox", "/library"]

CMD ["python", "-m", "comicsbot.main"]
