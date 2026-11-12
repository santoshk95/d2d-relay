# syntax=docker/dockerfile:1
# RELAY by PASDACS: the whole platform in one image.
#
#   web app       FastAPI on port 8000: what people use in the browser
#   AI engine     Claude Code, plus the Codex, Gemini and Antigravity CLIs (internal port 8090)
#   database      PostgreSQL 17, reachable only through its Unix socket inside the container
#   AI gateway    LiteLLM (internal port 4000); it starts only when a cloud AI provider is set up
#
# A process supervisor (supervisord under tini) starts the parts, restarts any part that stops and gives Docker one
# health status. Each part runs as its own user and gets only its own settings: the AI engine never sees the web app's
# keys, the database or the gateway's credentials.
#
#   docker build -t relay:1.0.0 .        (build context = the repository root)
#   docker compose up -d                 (docker-compose.yml; see docs/single-container.md)
#
# The per-part images (webapp/, agent/, litellm/, orchestrator/ with docker-compose.dev.yml) stay for development, the
# test suites and Kubernetes.

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie
ARG NODE_IMAGE=node:22.23.4-trixie-slim
# Antigravity CLI: downloaded from Google's update manifest and checked against its sha512, unless AGY_IMAGE names an
# image that already has /usr/local/bin/agy (for example the agent-antigravity development image, to keep its version).
ARG AGY_IMAGE=agy-download

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS agy-download
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* \
 && m=$(curl -fsSL https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json) \
 && url=$(echo "$m" | sed -n 's/.*"url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p') \
 && sum=$(echo "$m" | sed -n 's/.*"sha512"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p') \
 && curl -fsSL -o /tmp/agy.pkg "$url" && echo "$sum  /tmp/agy.pkg" | sha512sum -c - \
 && case "$url" in *.tar.gz*) tar -xzf /tmp/agy.pkg -C /tmp antigravity && mv /tmp/antigravity /usr/local/bin/agy ;; \
                          *) mv /tmp/agy.pkg /usr/local/bin/agy ;; esac \
 && chmod 755 /usr/local/bin/agy

FROM ${AGY_IMAGE} AS agy

FROM ${PYTHON_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Users: `agent` (uid 1000, like the Claude login volume it shares with other tools) runs the AI engine; `relay` runs
# the web app and the gateway; PostgreSQL runs as `postgres`. Project folders are shared through the group relaydata.
RUN groupadd --gid 1000 agent && useradd --uid 1000 --gid agent --create-home --shell /usr/sbin/nologin agent \
 && groupadd --gid 1001 relay && useradd --uid 1001 --gid relay --create-home --shell /usr/sbin/nologin relay \
 && groupadd --gid 1002 relaydata && usermod -aG relaydata agent && usermod -aG relaydata relay

# System packages: tini (PID 1), PostgreSQL 17 (Debian 13's own; no cluster is made at build time), ffmpeg (video key
# frames for Start from an idea), unixODBC + Microsoft's ODBC Driver 18 (Fabric connections). If Microsoft has not
# published the driver for this Debian release the build goes on, and Fabric connections report the missing driver.
RUN mkdir -p /etc/postgresql-common/createcluster.d \
 && echo "create_main_cluster = false" > /etc/postgresql-common/createcluster.d/relay.conf \
 && apt-get update && apt-get install -y --no-install-recommends \
      tini ca-certificates curl unixodbc ffmpeg postgresql-17 postgresql-client-17 \
 && . /etc/os-release \
 && (curl -fsSL -o /tmp/ms.deb "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" \
     && dpkg -i /tmp/ms.deb && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
     || echo "msodbcsql18 is not available for Debian ${VERSION_ID}: Fabric connections will not work") \
 && rm -rf /var/lib/apt/lists/* /tmp/ms.deb /var/lib/postgresql/17 /etc/postgresql/17

# Node.js 22 (the AI engine's CLIs, the visual factory, and the brand engine the web app runs for report themes)
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node /usr/local/include/node /usr/local/include/node
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version

# The AI engine's command-line tools, pinned to the versions the platform was tested with. They are owned by root, so
# they cannot update themselves.
ARG CLAUDE_CODE_VERSION=2.1.318
ARG PBIVIZ_VERSION=7.2.1
ARG CODEX_VERSION=0.163.0
ARG GEMINI_VERSION=0.65.0
RUN npm install -g --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "powerbi-visuals-tools@${PBIVIZ_VERSION}" "@openai/codex@${CODEX_VERSION}" "@google/gemini-cli@${GEMINI_VERSION}" \
 && npm cache clean --force && claude --version && codex --version
COPY --from=agy /usr/local/bin/agy /usr/local/bin/agy

# Python: one environment for the web app and the AI engine (the AI engine's packages are the same pinned versions as
# the web app's, plus Playwright), and the supervisor. The gateway gets its own environment below.
COPY webapp/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt "playwright==1.63.0" "supervisor==4.3.0" && rm /tmp/requirements.txt
# Headless Chromium: the display check, PDF/PNG renders and `genbi visual test`
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*
# The AI gateway: LiteLLM in its own environment (prisma: LiteLLM's error handler imports it; no database is used)
RUN python -m venv /opt/relay/gateway \
 && /opt/relay/gateway/bin/pip install "litellm[proxy]==1.104.8" "prisma==0.15.0"

# Visual factory: one shared node_modules for every custom visual the AI engine builds (Visual Atlas deps + d3), the
# Visual Atlas framework (common/), its 13 families as examples and the starter visual.
COPY visual_factory/package.json /opt/genbi/vkit/package.json
RUN cd /opt/genbi/vkit && npm install --no-audit --no-fund && npm cache clean --force
COPY visual-atlas/visuals /tmp/atlas
COPY visual-atlas/tools/mk_caps.js visual_factory/tsconfig.json visual_factory/eslint.config.mjs /opt/genbi/vkit/
COPY visual_factory/starter /opt/genbi/vkit/starter
RUN mv /tmp/atlas/common /opt/genbi/vkit/common && mkdir /opt/genbi/vkit/families \
 && for d in /tmp/atlas/atlas*; do n=$(basename "$d"); mkdir -p "/opt/genbi/vkit/families/$n"; \
      cp -r "$d/caps.js" "$d/pbiviz.json" "$d/src" "$d/style" "$d/assets" "/opt/genbi/vkit/families/$n/"; \
      rm -rf "/opt/genbi/vkit/families/$n/src/common" "/opt/genbi/vkit/families/$n/style/atlas.less"; done \
 && rm -rf /tmp/atlas && mkdir -p /opt/genbi/vkit/builds \
 && chown -R agent:agent /opt/genbi/vkit/node_modules /opt/genbi/vkit/builds

# The other CLIs' settings: Gemini's system settings, Antigravity's in the AI engine user's home
COPY agent/runner-config/gemini-settings.json /etc/gemini-cli/settings.json
COPY --chown=agent:agent agent/runner-config/antigravity-settings.json /home/agent/.gemini/antigravity-cli/settings.json

# Relay itself: the toolkit, the packaged custom visuals, the AI engine's service, the web app, the default model
# lists, the visual library a new install starts with, and the container's own scripts.
COPY genbi_kit /opt/genbi/genbi_kit
COPY custom_visuals /opt/genbi/visuals
COPY agent/server.py agent/runners.py agent/probe_models.py agent/bash_guard.py /opt/genbi/
# Claude Code's policy for the AI engine (managed settings: nothing in a project folder or the agent's home can change
# it): file tools only inside the dashboard's folder, the shell only for `genbi` (bash_guard.py), no web, no sub-agents
COPY agent/managed-settings.json /etc/claude-code/managed-settings.json
COPY config/models.json config/house-models.json /opt/genbi/config/
COPY webapp/app /srv/app
COPY webapp/static /srv/static
COPY visual-library /opt/relay/seed/library
COPY --chown=relay:relay litellm/d2d_auth.py /opt/relay/gateway-app/
COPY docker/supervisord.conf docker/postgres.conf docker/pg_hba.conf docker/pg_ident.conf /etc/relay/
COPY docker/entrypoint.sh /opt/relay/bin/entrypoint
COPY docker/relay_init.py /opt/relay/bin/relay-init
COPY docker/launch.py /opt/relay/bin/launch
COPY docker/watchdog.py /opt/relay/bin/watchdog
COPY docker/gateway.sh /opt/relay/bin/gateway
COPY docker/relay_ctl.py /opt/relay/bin/relay-ctl
# genbi runs with python -P: it never imports from the folder the AI works in (a genbi_kit/ or json.py written there
# would otherwise run as the toolkit, with the AI engine's rights; security audit 2026-11-11)
RUN sed -i 's/\r$//' /opt/relay/bin/* /etc/relay/* \
 && chmod 755 /opt/relay/bin/* && chmod 644 /etc/relay/* \
 && ln -s /opt/relay/bin/relay-ctl /usr/local/bin/relay-ctl \
 && printf '#!/bin/sh\nexec /usr/local/bin/python -P -m genbi_kit.cli "$@"\n' > /usr/local/bin/genbi && chmod 755 /usr/local/bin/genbi \
 && mkdir -p /data /opt/genbi/library /home/agent/.claude /home/agent/.codex /opt/agy-login \
 && chown agent:agent /home/agent/.claude /home/agent/.codex && chown -R agent:agent /home/agent/.gemini \
 && chown relay:relay /opt/relay/gateway-app \
 && python -m compileall -q /srv/app /opt/genbi/genbi_kit /opt/genbi/server.py /opt/genbi/runners.py

ARG RELAY_VERSION=1.0.0
ARG RELAY_COMMIT=
LABEL org.opencontainers.image.title="RELAY by PASDACS" \
      org.opencontainers.image.description="The Relay platform in one container: web app, AI engine, database and AI gateway" \
      org.opencontainers.image.vendor="PASDACS" \
      org.opencontainers.image.url="https://pasdacs.com" \
      org.opencontainers.image.version="${RELAY_VERSION}" \
      org.opencontainers.image.revision="${RELAY_COMMIT}" \
      relay.commit="${RELAY_COMMIT}"
# Shared by every part (each part's own settings are written at start-up: docker/relay_init.py)
ENV RELAY_VERSION=${RELAY_VERSION} RELAY_COMMIT=${RELAY_COMMIT} \
    PYTHONPATH=/opt/genbi WORKSPACES=/data/projects GENBI_VISUALS=/opt/genbi/visuals GENBI_VKIT=/opt/genbi/vkit \
    GENBI_LIBRARY=/opt/genbi/library DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 NO_UPDATE_NOTIFIER=1

WORKDIR /srv
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=20s --start-period=180s --retries=3 CMD ["/opt/relay/bin/relay-ctl", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/relay/bin/entrypoint"]
CMD ["start"]
