# Build context is the spectra-sherpa package root:
#
#   docker build -f frontend/Dockerfile .

# Build Stage
FROM node:22-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS build-stage

WORKDIR /build/spectra-sherpa/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./
COPY src/spectra_sherpa/data/plate_formats_v1.json \
    /build/spectra-sherpa/src/spectra_sherpa/data/plate_formats_v1.json
# Vite outputs to ../src/spectra_sherpa/static within the package tree.
RUN npm run build

# Production Stage
FROM nginx:stable-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951 AS production-stage

# nginx's native error records contain raw request URLs. Sanitize the private
# stderr pipe before anything reaches Docker logs; keep lifecycle forwarding.
RUN apk add --no-cache python3 \
    && sed -i 's|^[[:space:]]*error_log[[:space:]].*|error_log stderr warn;|' /etc/nginx/nginx.conf \
    && grep -q '^error_log stderr warn;' /etc/nginx/nginx.conf
COPY frontend/nginx_safe_logs.py /usr/local/bin/nginx_safe_logs.py

COPY --from=build-stage /build/spectra-sherpa/src/spectra_sherpa/static /usr/share/nginx/html

# Copy custom nginx config
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

STOPSIGNAL SIGQUIT
ENTRYPOINT ["python3", "/usr/local/bin/nginx_safe_logs.py", "/docker-entrypoint.sh"]
CMD ["nginx", "-e", "stderr", "-g", "daemon off;"]
