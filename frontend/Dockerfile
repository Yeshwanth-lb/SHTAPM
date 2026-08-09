# syntax=docker/dockerfile:1
# SHTAPM frontend — WIRED-EMPTY skeleton (P0).
# The real image (npm ci → vite build → nginx serve, TRD §02.5) lands in P5.
FROM node:20-alpine
WORKDIR /app
COPY package.json .
# RUN npm ci            # enabled in P5 (needs package-lock.json)
COPY . .
# CMD ["npm", "run", "dev"]   # dev; production build+nginx in P5
CMD ["node", "-e", "console.log('SHTAPM frontend placeholder — implemented in P5')"]
