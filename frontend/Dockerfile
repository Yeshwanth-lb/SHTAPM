# syntax=docker/dockerfile:1
# SHTAPM frontend — minimum TRD-compatible multi-stage build (P0 offline-stack).
# Build the current minimal React live-telemetry app, serve dist/ via nginx.
# No lockfile in the repo yet → npm install (P5 adds the lockfile). No Aurora/
# Tailwind/charts/auth (P5).

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app

# Optional corporate/proxy root CA(s) for TLS-inspected networks (e.g. Zscaler).
# Drop <name>.crt files into frontend/certs/ (gitignored; never committed).
# They are concatenated into a PEM and ADDED to Node's trust via
# NODE_EXTRA_CA_CERTS — TLS verification is NEVER disabled (no strict-ssl=false,
# no NODE_TLS_REJECT_UNAUTHORIZED). Empty by default → no-op on normal networks.
COPY certs/ /tmp/certs/
RUN cat /tmp/certs/*.crt > /usr/local/share/ca-extra.pem 2>/dev/null || true
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-extra.pem

COPY package.json ./
RUN npm install
COPY . .
# Bake the WebSocket URL for the browser at build time (Vite inlines VITE_*).
# Defaults to the local backend host port; overridden via compose build.args.
ARG VITE_WS_URL=ws://localhost:8002/ws
ENV VITE_WS_URL=$VITE_WS_URL
RUN npm run build

# ---- runtime stage (nginx static) ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
