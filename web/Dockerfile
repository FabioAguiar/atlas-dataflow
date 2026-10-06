# Production bases: readable tags plus immutable multi-platform index digests
# (linux/amd64 and linux/arm64). Updating a digest is a deliberate, reviewed
# repository change (docs/operations/production-build-provenance.md).
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build

# When the canonical builder requests an SBOM attestation, also scan this
# stage so the SBOM lists the npm dependency graph that produced the bundle.
ARG BUILDKIT_SBOM_SCAN_STAGE=true

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

FROM nginx:alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2 AS serve

# OCI source/revision metadata. The revision is supplied only by the canonical
# builder (scripts/build-production-images.sh), which derives it from the clean
# Git HEAD; no clock-derived "created" label is added.
ARG ATLAS_SOURCE_REVISION=""
LABEL org.opencontainers.image.source="https://github.com/FabioAguiar/atlas-dataflow" \
      org.opencontainers.image.revision="${ATLAS_SOURCE_REVISION}" \
      org.opencontainers.image.title="atlas-dataflow-web"

# Set by the canonical builder from the selected commit timestamp; used only to
# keep generated account metadata independent of the build clock.
ARG SOURCE_DATE_EPOCH

COPY --from=build /app/nginx.default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# The base image writes its pid to root-owned /run (/var/run is only a
# symlink, so chowning it does not help); move it to /tmp for the non-root
# user and drop the master-only "user" directive. BusyBox adduser stamps the
# build day into /etc/shadow; the canonical build pins that field to the
# commit day so the image does not depend on the build clock.
RUN sed -i -e 's#^pid .*#pid /tmp/nginx.pid;#' -e '/^user /d' /etc/nginx/nginx.conf \
    && addgroup -S -g 10001 atlas \
    && adduser -S -D -H -u 10001 -G atlas atlas \
    && if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then \
        sed -i "s/^\(atlas:[^:]*:\)[0-9]*:/\1$((SOURCE_DATE_EPOCH / 86400)):/" /etc/shadow; \
    fi \
    && chown -R atlas:atlas /var/cache/nginx /var/run /var/log/nginx /etc/nginx/conf.d

EXPOSE 80

USER atlas

CMD ["nginx", "-g", "daemon off;"]
