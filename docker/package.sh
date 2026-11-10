#!/usr/bin/env bash
# Builds the release package: dist/relay-<version>/ = the image file and everything needed to run Relay on another PC
# (Windows, Linux or macOS). Needs the image relay:<version> (relay build; or the release build from a clean commit).
#   bash docker/package.sh                 (Git Bash on Windows, from the repository root)
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
VER="${RELAY_VERSION:-1.0.0}"
IMG="relay:$VER"
OUT="dist/relay-$VER"
docker image inspect "$IMG" >/dev/null 2>&1 || { echo "There is no image $IMG. Build it first: relay build"; exit 1; }
COMMIT="$(docker image inspect -f '{{index .Config.Labels "relay.commit"}}' "$IMG")"
rm -rf "$OUT"
mkdir -p "$OUT/config" "$OUT/daxcheck" "$OUT/data/projects" "$OUT/data/backups" "$OUT/data/library"

# the compose file without its build section (the package has no source)
python - "$OUT/docker-compose.yml" <<'EOF'
import re, sys
text = open("docker-compose.yml", encoding="utf-8").read()
text = re.sub(r"\n    build:\n(?:      .*\n)+", "\n", text)
text = text.replace("#   relay.cmd start               on this PC (adds the office network address when it is here: docker-compose.lan.yml)\n",
                    "#   relay.cmd start               Windows (relay.sh start on Linux or macOS)\n")
assert "build:" not in text
open(sys.argv[1], "w", encoding="utf-8", newline="\n").write(text)
EOF
cp docker-compose.lan.yml relay.cmd relay.ps1 relay.sh .env.example "$OUT/"
cp config/models.json config/house-models.json "$OUT/config/"
cp daxcheck/daxcheck.ps1 "$OUT/daxcheck/"
printf '@echo off\r\nrem Starts the Relay DAX checker for this package (queue: data\\projects\\.daxcheck). Leave it running while Relay is used.\r\nstart "Relay DAX checker" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%%~dp0daxcheck.ps1" -Queue "%%~dp0..\\data\\projects\\.daxcheck" %%*\r\n' > "$OUT/daxcheck/start-daxcheck.cmd"
cp docs/single-container.md "$OUT/GUIDE.md"
sed -e "s/{{VERSION}}/$VER/g" -e "s/{{COMMIT}}/${COMMIT:0:12}/g" -e "s/{{DATE}}/$(date +%Y-%m-%d)/g" docker/package-README.md > "$OUT/README.md"
chmod +x "$OUT/relay.sh"

echo "Saving the image ($IMG, commit ${COMMIT:0:12}) ..."
docker save "$IMG" relay:latest | gzip > "$OUT/relay-$VER.tar.gz"
( cd "$OUT" && sha256sum "relay-$VER.tar.gz" > SHA256SUMS )
du -sh "$OUT" "$OUT/relay-$VER.tar.gz"
echo "Package: $OUT"
