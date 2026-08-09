# syntax=docker/dockerfile:1
# SHTAPM backend — WIRED-EMPTY skeleton (P0).
# The real image (deps install + uvicorn CMD) is completed in P4.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt   # enabled in P4
COPY . .
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]   # P4
CMD ["python", "-c", "print('SHTAPM backend placeholder — implemented in P4')"]
