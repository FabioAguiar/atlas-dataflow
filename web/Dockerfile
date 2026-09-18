FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src ./src

ARG VITE_API_BASE_URL=""
ARG VITE_ENABLE_ADMIN="false"
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_ENABLE_ADMIN=${VITE_ENABLE_ADMIN}

RUN npm run build

FROM nginx:alpine AS serve

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

RUN addgroup -S -g 10001 atlas \
    && adduser -S -D -H -u 10001 -G atlas atlas \
    && chown -R atlas:atlas /var/cache/nginx /var/run /var/log/nginx /etc/nginx/conf.d

EXPOSE 80

USER atlas

CMD ["nginx", "-g", "daemon off;"]
