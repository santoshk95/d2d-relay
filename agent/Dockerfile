# Relay's AI engine (development and test image; Relay itself runs as one container: ../Dockerfile): Claude Code CLI
# + the genbi toolkit + the visual factory. Build context = the repository root.
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code powerbi-visuals-tools@7.2.1 && npm cache clean --force
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir \
    fastapi==0.115.6 uvicorn==0.32.1 duckdb==1.2.2 pyyaml==6.0.2 playwright==1.63.0
# Headless Chromium: `genbi visual test` renders a new custom visual and screenshots it for Claude to look at.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN /opt/venv/bin/playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*
# Visual factory: one shared node_modules for every custom visual the agent builds (Visual Atlas deps + d3),
# the Visual Atlas framework (common/), its 13 families as examples and the starter visual.
COPY visual_factory/package.json /opt/genbi/vkit/package.json
RUN cd /opt/genbi/vkit && npm install --no-audit --no-fund && npm cache clean --force && chown -R node:node node_modules
COPY visual-atlas/visuals /tmp/atlas
COPY visual-atlas/tools/mk_caps.js visual_factory/tsconfig.json visual_factory/eslint.config.mjs /opt/genbi/vkit/
COPY visual_factory/starter /opt/genbi/vkit/starter
RUN mv /tmp/atlas/common /opt/genbi/vkit/common && mkdir /opt/genbi/vkit/families \
    && for d in /tmp/atlas/atlas*; do n=$(basename "$d"); mkdir -p "/opt/genbi/vkit/families/$n"; \
         cp -r "$d/caps.js" "$d/pbiviz.json" "$d/src" "$d/style" "$d/assets" "/opt/genbi/vkit/families/$n/"; \
         rm -rf "/opt/genbi/vkit/families/$n/src/common" "/opt/genbi/vkit/families/$n/style/atlas.less"; done \
    && rm -rf /tmp/atlas && mkdir -p /opt/genbi/vkit/builds && chown node:node /opt/genbi/vkit/builds
# Review gates: Microsoft's PBIR JSON schemas are checked with jsonschema (the schemas ship in genbi_kit/schemas).
RUN /opt/venv/bin/pip install --no-cache-dir jsonschema==4.26.0 referencing==0.37.0
# P10 (Start from an idea): `genbi read` — Word, Excel, PowerPoint and PDF readers; ffmpeg for video key frames.
RUN /opt/venv/bin/pip install --no-cache-dir python-docx==1.1.2 openpyxl==3.1.5 python-pptx==1.0.2 pypdf==5.1.0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# P16 (AI SDLC): `genbi repo` — git in pure Python (dulwich); the agent never runs git itself
RUN /opt/venv/bin/pip install --no-cache-dir dulwich==1.2.21
COPY genbi_kit /opt/genbi/genbi_kit
COPY custom_visuals /opt/genbi/visuals
COPY agent/server.py agent/runners.py agent/probe_models.py agent/bash_guard.py /opt/genbi/
COPY agent/managed-settings.json /etc/claude-code/managed-settings.json
RUN printf '#!/bin/sh\nexec /opt/venv/bin/python -m genbi_kit.cli "$@"\n' > /usr/local/bin/genbi && chmod +x /usr/local/bin/genbi \
    && mkdir -p /home/node/.claude /data/projects /opt/genbi/library && chown -R node:node /home/node /data
# node (uid 1000) also owns the Claude login in the shared claude-api-auth volume.
USER node
# Bash timeouts: building a visual (pbiviz: TypeScript, ESLint, webpack) can take a few minutes.
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/opt/genbi GENBI_VISUALS=/opt/genbi/visuals \
    GENBI_VKIT=/opt/genbi/vkit GENBI_LIBRARY=/opt/genbi/library \
    CLAUDE_CONFIG_DIR=/home/node/.claude DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    BASH_DEFAULT_TIMEOUT_MS=300000 BASH_MAX_TIMEOUT_MS=600000 \
    WORKSPACES=/data/projects PYTHONUNBUFFERED=1
WORKDIR /opt/genbi
# The commit this image was built from (Relay Doctor; see webapp/Dockerfile).
ARG RELAY_COMMIT=
LABEL relay.commit=$RELAY_COMMIT
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/health')"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090"]
