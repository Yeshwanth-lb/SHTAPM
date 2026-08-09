# syntax=docker/dockerfile:1
# SHTAPM frontend — minimum TRD-compatible multi-stage build (P0 offline-stack).
# Build the current minimal React live-telemetry app, serve dist/ via nginx.
# No lockfile in the repo yet → npm install (P5 adds the lockfile). No Aurora/
# Tailwind/charts/auth (P5).

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- runtime stage (nginx static) ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
