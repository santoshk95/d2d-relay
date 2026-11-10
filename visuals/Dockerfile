# Builds the Gen BI custom visuals (.pbiviz) and the prototype bundle.
#   docker build -t genbi-visuals visuals
#   docker run --rm -v "<out dir>:/out" genbi-visuals
FROM node:20-bookworm-slim
RUN npm install -g powerbi-visuals-tools@7.2.1 esbuild@0.28.2 && npm cache clean --force
WORKDIR /visuals
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN bash build.sh
CMD ["sh", "-c", "cp -r dist/. /out/ && ls /out"]
