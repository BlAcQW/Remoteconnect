# RemoteConnect backend (FastAPI + uvicorn)
FROM python:3.12-slim

# System libs needed by asyncpg/Pillow/etc. — keep minimal.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache the dep layer
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r backend/requirements.txt

# Source is mounted by docker-compose for hot-reload, but we COPY a snapshot
# so the image is runnable on its own.
COPY backend ./backend

EXPOSE 8765
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765", "--reload"]
