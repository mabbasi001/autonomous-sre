FROM python:3.12-slim

WORKDIR /srv/backend

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY backend/pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY backend/ ./

EXPOSE 8000

# Default command is the API; compose overrides for worker/scheduler.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
