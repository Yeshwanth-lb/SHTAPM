# syntax=docker/dockerfile:1
# SHTAPM backend — minimum real FastAPI image (P0 offline-stack gate).
# Runs the existing app.main:app (MQTT telemetry ingestion + WS fan-out).
# No DB/auth/persistence wired here (P4).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "[REDACTED_MOCK_PII]", "--port", "8000"]
