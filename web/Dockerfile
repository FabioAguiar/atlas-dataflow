FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.node.json ./
COPY src ./src

ARG VITE_API_BASE_URL=""
ARG VITE_ENABLE_ADMIN="false"
ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_PUBLISHABLE_KEY=""
ARG VITE_TURNSTILE_SITE_KEY=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_ENABLE_ADMIN=${VITE_ENABLE_ADMIN}
ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY}
ENV VITE_TURNSTILE_SITE_KEY=${VITE_TURNSTILE_SITE_KEY}

RUN npm run build

FROM nginx:alpine AS serve

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# The base image writes its pid to root-owned /run (/var/run is only a
# symlink, so chowning it does not help); move it to /tmp for the non-root
# user and drop the master-only "user" directive.
RUN sed -i -e 's#^pid .*#pid /tmp/nginx.pid;#' -e '/^user /d' /etc/nginx/nginx.conf \
    && addgroup -S -g 10001 atlas \
    && adduser -S -D -H -u 10001 -G atlas atlas \
    && chown -R atlas:atlas /var/cache/nginx /var/run /var/log/nginx /etc/nginx/conf.d

EXPOSE 80

USER atlas

CMD ["nginx", "-g", "daemon off;"]
