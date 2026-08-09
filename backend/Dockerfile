# syntax=docker/dockerfile:1
# SHTAPM backend — minimum real FastAPI image (P0 offline-stack gate).
# Runs the existing app.main:app (MQTT telemetry ingestion + WS fan-out).
# No DB/auth/persistence wired here (P4).
FROM python:3.11-slim
WORKDIR /app

# Optional corporate/proxy root CA(s) for TLS-inspected networks (e.g. Zscaler).
# Drop <name>.crt files into backend/certs/ (gitignored; never committed).
# Empty by default → this is a no-op on normal networks and standard PyPI TLS
# verification is used. TLS verification is NEVER disabled.
COPY certs/ /usr/local/share/ca-certificates/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pip uses its bundled certifi store by default; point it at the SYSTEM bundle
# (which now includes any CA added above) so verification stays ON and also
# trusts a corporate root when present. Standard system roots on normal networks.
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "[REDACTED_MOCK_PII]", "--port", "8000"]
