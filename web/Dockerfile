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

# Render the public CSP connect-src from the public VITE_SUPABASE_URL build
# input: only its exact http(s) origin is added (never a path, credentials or a
# scheme-wide source). Empty adds nothing; an unusable URL fails the build.
COPY nginx.conf ./nginx.conf.template
RUN node -e ' \
  const fs = require("fs"); \
  const marker = "__ATLAS_SUPABASE_CONNECT_SRC__"; \
  const fail = (reason) => { console.error("VITE_SUPABASE_URL rejected for CSP: " + reason); process.exit(1); }; \
  const raw = String(process.env.VITE_SUPABASE_URL || "").trim(); \
  let source = ""; \
  if (raw) { \
    let url; \
    try { url = new URL(raw); } catch { fail("not a parseable URL"); } \
    if (url.protocol !== "https:" && url.protocol !== "http:") fail("scheme must be http or https"); \
    if (url.username || url.password) fail("credentials are not allowed"); \
    const allowed = "abcdefghijklmnopqrstuvwxyz0123456789.-:[]"; \
    if (!url.hostname || ![...url.host].every((c) => allowed.includes(c))) fail("unsupported host"); \
    source = " " + url.origin; \
  } \
  const template = fs.readFileSync("nginx.conf.template", "utf8"); \
  if (template.split(marker).length !== 2) fail("template must contain the marker exactly once"); \
  fs.writeFileSync("nginx.default.conf", template.replace(marker, source)); \
  '

FROM nginx:alpine AS serve

COPY --from=build /app/nginx.default.conf /etc/nginx/conf.d/default.conf
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
