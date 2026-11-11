# Export the local database (wiki pages, chunks with embeddings) for the server.
#   powershell -ExecutionPolicy Bypass -File scripts\export_db.ps1
# Writes backups\build_advisor-<date>.dump; copy it to the server and run
# deploy/restore_db.sh there (see docs/deploy-hetzner.md).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$name = "build_advisor-$(Get-Date -Format 'yyyy-MM-dd').dump"
New-Item -ItemType Directory -Force backups | Out-Null

# pg_dump writes inside the container; copying the file out keeps it binary-safe
# (PowerShell's ">" would re-encode it).
docker compose exec -T db pg_dump -U build_advisor -Fc -Z 6 -f "/tmp/$name" build_advisor
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
docker compose cp "db:/tmp/$name" "backups\$name"
docker compose exec -T db rm "/tmp/$name"

$size = [math]::Round((Get-Item "backups\$name").Length / 1MB, 1)
Write-Output "Wrote backups\$name ($size MB)"
docker compose exec -T db psql -U build_advisor -d build_advisor -At -c @"
select 'wiki pages: ' || count(*) from wiki_document
union all select 'chunks: ' || count(*) || ' (' || count(embedding) || ' embedded)' from wiki_chunk
union all select 'patch: ' || string_agg(distinct patch, ', ') from wiki_document;
"@
Write-Output ""
Write-Output "Next: scp backups\$name root@<server-ip>:/srv/build-advisor/backups/"
Write-Output "Then on the server: bash /srv/build-advisor/deploy/restore_db.sh backups/$name"
