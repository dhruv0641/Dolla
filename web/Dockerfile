FROM node:22-alpine AS build

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
COPY config /app/config
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runtime

WORKDIR /app/web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build --chown=node:node /app/web/.next ./.next
COPY --from=build --chown=node:node /app/web/next.config.ts ./next.config.ts
COPY --from=build --chown=node:node /app/config /app/config
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
