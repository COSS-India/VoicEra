FROM node:24-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* are inlined at build time; API_PROXY_TARGET is read at runtime in next.config.ts.
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG NEXT_PUBLIC_RUNTIME_WS_URL

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_RUNTIME_WS_URL=$NEXT_PUBLIC_RUNTIME_WS_URL
ENV API_PROXY_TARGET=http://api:8000

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
