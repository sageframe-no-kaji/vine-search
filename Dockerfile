FROM debian:trixie-slim AS novnc-assets
RUN apt-get update \
    && apt-get download novnc \
    && mkdir -p /export \
    && dpkg-deb --extract novnc*.deb /export \
    && dpkg-deb --field novnc*.deb Version > /export/usr/share/novnc/VERSION.debian \
    && cp /export/usr/share/novnc/VERSION.debian /export/usr/share/doc/novnc/VERSION.debian \
    && dpkg-deb --field novnc*.deb Package Version Source Architecture \
       > /export/usr/share/doc/novnc/SOURCE.debian \
    && sha256sum novnc*.deb > /export/usr/share/doc/novnc/package.sha256

FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PATH="/opt/venv/bin:$PATH" \
    VINE_SEARCH_DATA_DIR=/data \
    VINE_SEARCH_SESSION_DIR=/session

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    ca-certificates fonts-liberation xvfb x11vnc websockify openbox \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.9.5

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache \
    && groupadd --gid 1000 vine \
    && useradd --uid 1000 --gid vine --create-home --shell /usr/sbin/nologin vine \
    && mkdir -p /data /session \
    && chown vine:vine /data /session \
    && chmod 700 /session

COPY src ./src
COPY README.md ./
RUN uv sync --locked --no-dev
COPY docker/healthcheck.py /app/docker/healthcheck.py
COPY docker/verify-login.py /app/docker/verify-login.py
COPY docker/third-party-sources.py /app/docker/third-party-sources.py
COPY docker/LICENSE.playwright /app/docker/LICENSE.playwright
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY docs/debian-packages.md /app/docs/debian-packages.md
COPY --from=novnc-assets /export/usr/share/novnc /usr/share/novnc
COPY --from=novnc-assets /export/usr/share/doc/novnc /usr/share/doc/novnc
COPY docker/prepare-novnc.py /app/docker/prepare-novnc.py
RUN python /app/docker/prepare-novnc.py
USER vine
EXPOSE 8765
ENTRYPOINT ["python", "-m", "vine_search"]
CMD ["web"]
