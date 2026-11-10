# Build and test environment for the Visual Atlas Power BI custom visuals.
#   docker build -t visual-atlas -f docker/Dockerfile .
#   docker run --rm -v "$PWD":/work -w /work visual-atlas make all
# Node 22 + powerbi-visuals-tools (pbiviz) to package, Python + Playwright Chromium for the mock-host tests.
FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv make zip unzip \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g powerbi-visuals-tools@7.2.1

RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir playwright==1.63.0 jsonschema==4.26.0 \
 && /opt/venv/bin/playwright install --with-deps chromium
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /work
CMD ["make", "all"]
