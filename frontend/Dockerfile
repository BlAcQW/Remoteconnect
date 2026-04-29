# RemoteConnect frontend (Next.js 14)
FROM node:22-alpine

WORKDIR /app

# Cache the dep layer
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

# Source mounted by docker-compose for hot reload; copy as fallback.
COPY frontend ./

EXPOSE 3000
ENV PORT=3000
CMD ["npm", "run", "dev"]
