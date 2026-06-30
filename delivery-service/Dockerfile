# syntax=docker/dockerfile:1

# ---- build stage ---------------------------------------------------------
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ---- runtime stage -------------------------------------------------------
FROM node:22-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY --from=build /app/dist ./dist

# Run as the unprivileged user that ships with the node image.
USER node

# Cloud Run injects $PORT; default to 8080 for local parity.
ENV PORT=8080
EXPOSE 8080
CMD ["node", "dist/src/index.js"]
