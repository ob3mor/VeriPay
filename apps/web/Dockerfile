# VeriPay web (apps/web) — dev server container for the compose demo.
# Build from the REPO ROOT (compose sets context: ../..) so the npm
# workspace — including @veripay/api-contracts — is available.
# The static EXPORT build (output: 'export') is what Azure Static Web Apps
# serves in PROFILE B; inside compose we run `next dev` so the demo stack is
# live-editable and no export/re-serve plumbing is needed locally.

FROM node:22-alpine

WORKDIR /app

# Workspace manifests first (cached dependency layer).
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/api-contracts/package.json packages/api-contracts/package.json
RUN npm ci --no-audit --no-fund

# Sources.
COPY packages/api-contracts/tsconfig.json packages/api-contracts/tsconfig.json
COPY packages/api-contracts/src packages/api-contracts/src
COPY apps/web ./apps/web

WORKDIR /app/apps/web

EXPOSE 3000

CMD ["npm", "run", "dev"]
