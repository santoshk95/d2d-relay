<#
D2D Relay: move a one-container install (container d2d-relay, everything inside) to the split layout of
docker-compose.yml: d2d-relay-db, d2d-relay-web and d2d-relay-admin (+ d2d-relay-tunnel).

Run it in the deploy folder (the one with docker-compose.yml, .env and data\) after `git pull` brought this file:

    powershell -ExecutionPolicy Bypass -File docker\move-to-split.ps1 [-Tunnel]

1. Refuses while the AI engine is running a build (a restart would cut it off).
2. Stops the old web app and AI engine, then dumps the database into data\backups (pre-split-<time>.dump).
3. Stops the old container. It is kept, with its own database untouched, for a rollback.
4. Adds RELAY_DB_PASSWORD to .env when it is missing (a new random one).
5. Puts the dump into the new database volume (d2d-relay-db-data), which loads it on its first start.
6. Builds the image from this commit and starts the database, the public site and the admin portal (-Tunnel: the
   tunnel too), and waits until they are healthy.

Rollback (nothing done after the move is kept):  docker compose down ; docker start d2d-relay
#>
param([switch]$Tunnel, [switch]$NoBuild)
$ErrorActionPreference = 'Stop'
function Say($text) { Write-Host "move-to-split: $text" }
function Fail($text) { Write-Host "move-to-split: STOPPED: $text" -ForegroundColor Red; exit 1 }

if (-not (Test-Path docker-compose.yml) -or -not (Test-Path .env)) { Fail 'run this in the deploy folder (docker-compose.yml and .env)' }
if (-not (Select-String -Path docker-compose.yml -Pattern 'RELAY_ROLE: database' -Quiet)) { Fail 'docker-compose.yml is not the split layout yet: git pull first' }
$old = docker ps -a --filter 'name=^d2d-relay$' --format '{{.Names}} {{.State}}'
if (-not $old) { Fail 'there is no old container d2d-relay to move from' }
$fresh = docker volume ls --filter 'name=^d2d-relay-db-data$' --format '{{.Name}}'
if ($fresh) {
  $has = docker run --rm --entrypoint sh -v d2d-relay-db-data:/data d2d-relay:latest -c 'test -f /data/postgres/PG_VERSION && echo yes || echo no'
  if ($has -eq 'yes') { Fail 'the new database volume d2d-relay-db-data already has a database: the move was done before' }
}

# 1. nothing running
if ($old -like '* running') {
  $busy = docker exec d2d-relay sh -c 'curl -fsS http://127.0.0.1:8090/health || true'
  if ($busy -match '"busy"\s*:\s*true' -or $busy -match '"build"\s*:\s*true') { Fail "the AI engine is running a build now; try again when it has finished ($busy)" }
  # 2. no more writes, then the dump
  Say 'stopping the old web app and AI engine'
  docker exec d2d-relay sh -c 'supervisorctl -c /run/relay/supervisord.conf stop web agent' | Out-Host
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $dump = "pre-split-$stamp.dump"
  Say "dumping the database to data\backups\$dump"
  docker exec d2d-relay relay-ctl db-dump "/data/backups/$dump" | Out-Host
  if ($LASTEXITCODE) { docker exec d2d-relay sh -c 'supervisorctl -c /run/relay/supervisord.conf start web agent' | Out-Null; Fail 'the dump failed; the old app is running again' }
  # 3. the old container stops (kept for a rollback)
  Say 'stopping the old container d2d-relay (kept, with its database, for a rollback)'
  docker stop -t 120 d2d-relay | Out-Null
} else {
  Fail 'the old container d2d-relay is not running: start it first, so its database can be dumped'
}
$backups = (Get-Content .env | Where-Object { $_ -match '^\s*RELAY_BACKUPS=(.+)$' } | ForEach-Object { $Matches[1].Trim() }) | Select-Object -Last 1
if (-not $backups) { $backups = '.\data\backups' }
$dumpPath = Join-Path (Resolve-Path $backups) $dump
if (-not (Test-Path $dumpPath)) { Fail "the dump $dumpPath is missing" }
Say ("dump: {0:N0} KB" -f ((Get-Item $dumpPath).Length / 1KB))

# 4. the database password
if (-not (Select-String -Path .env -Pattern '^\s*RELAY_DB_PASSWORD=\S' -Quiet)) {
  $bytes = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pw = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  $text = [IO.File]::ReadAllText((Resolve-Path .env))
  $nl = if ($text.EndsWith("`n")) { '' } else { "`n" }
  [IO.File]::AppendAllText((Resolve-Path .env), "$nl# the database container's password for the app (docker\move-to-split.ps1)`nRELAY_DB_PASSWORD=$pw`n", (New-Object Text.UTF8Encoding $false))
  Say 'added RELAY_DB_PASSWORD to .env'
}

# 5. the dump into the new database volume
docker volume create d2d-relay-db-data | Out-Null
$dir = Split-Path $dumpPath
docker run --rm --entrypoint sh -v d2d-relay-db-data:/data -v "${dir}:/in:ro" d2d-relay:latest -c "mkdir -p /data/import && cp /in/$dump /data/import/relay.dump && chmod 600 /data/import/relay.dump" | Out-Host
if ($LASTEXITCODE) { Fail 'could not put the dump into the new database volume' }

# 6. build and start
if (-not $NoBuild) {
  $env:RELAY_COMMIT = (git rev-parse HEAD).Trim()
  Say "building the image ($($env:RELAY_COMMIT.Substring(0, 8)))"
  docker compose build web
  if ($LASTEXITCODE) { Fail 'the build failed. Rollback: docker start d2d-relay' }
}
Say 'starting the database, the public site and the admin portal'
if ($Tunnel) { docker compose --profile tunnel up -d } else { docker compose up -d db web admin }
if ($LASTEXITCODE) { Fail 'docker compose up failed. Rollback: docker compose down ; docker start d2d-relay' }
foreach ($c in 'd2d-relay-db', 'd2d-relay-web', 'd2d-relay-admin') {
  $state = ''
  for ($i = 0; $i -lt 100 -and $state -ne 'healthy'; $i++) { Start-Sleep -Seconds 3; $state = docker inspect -f '{{.State.Health.Status}}' $c }
  if ($state -ne 'healthy') { Fail "$c is not healthy ($state): docker logs $c. Rollback: docker compose down ; docker start d2d-relay" }
  Say "$c is healthy"
}
docker logs d2d-relay-db 2>&1 | Select-String 'relay-init' | ForEach-Object { Say $_.Line }
Say 'done. Public site: http://127.0.0.1:8100 · admin portal: http://127.0.0.1:8102 (this PC only until Cloudflare Access is set up)'
Say "the old container d2d-relay stays stopped for a rollback; remove it when you are sure: docker rm d2d-relay"
