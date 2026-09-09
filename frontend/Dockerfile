FROM node:24-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* are inlined at build time; proxy targets are read at runtime in next.config.ts.
ARG NEXT_PUBLIC_API_URL=/api/v1

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV API_PROXY_TARGET=http://api:8000
ENV RUNTIME_PROXY_TARGET=http://runtime:7860

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
