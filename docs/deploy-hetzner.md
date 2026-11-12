# Deploying to a Hetzner CX23

One server (2 vCPU, 4 GB RAM, ~€5.49/month excl. VAT) runs everything with
`docker-compose.prod.yml`: Caddy (HTTPS) → gunicorn → Postgres + pgvector.
Wiki imports and indexing stay on your own machine; you copy the database over.

Commands marked **local** run in PowerShell in your project folder; **server**
commands run over SSH.

## 1. Create the server

1. **local** Make an SSH key if you don't have one: `ssh-keygen -t ed25519`
   (press Enter for the defaults). Your public key is in
   `~\.ssh\id_ed25519.pub`.
2. Hetzner Cloud console → *Add server*: location Falkenstein, Nuremberg or
   Helsinki; image **Ubuntu 24.04**; type **CX23** (cost-optimized); add your
   SSH key. Optional: enable Backups (+20%). Since mid-2026 many cheap types
   are often unavailable; `hcloud server-type describe cx23 -o json` shows
   availability per location. With 8 GB (e.g. CPX32) set `POB_POOL_SIZE=2`.
3. Note the server's IPv4 address. No domain? Use `<ip>.sslip.io`
   (e.g. `203.0.113.7.sslip.io`), which points to your IP and gets a real HTTPS
   certificate. With a domain, add an `A` record pointing to the IP.

## 2. Set up the server

```bash
# local
ssh root@<ip>
# server
curl -fsSL https://raw.githubusercontent.com/wahid/build-advisor/main/deploy/server-setup.sh | bash
```

This adds a 4 GB swap file, installs Docker, a firewall (SSH, HTTP, HTTPS
only), automatic security updates, a `deploy` user, clones the repo into `/srv/build-advisor` and adds a
nightly database backup. (Private repo? Clone with a deploy key instead and run
the script with `REPO=git@github.com:wahid/build-advisor.git`.)

```bash
# server
cd /srv/build-advisor
cp .env.prod.example .env.prod
nano .env.prod     # DOMAIN, DJANGO_SECRET_KEY, POSTGRES_PASSWORD, LLM_API_KEY
```

## 3. Copy your database

The wiki pages and the 27k chunks with their embeddings come from your local
database (about 140 MB as a dump).

```powershell
# local (PowerShell, in the project folder)
powershell -ExecutionPolicy Bypass -File scripts\export_db.ps1
scp backups\build_advisor-<date>.dump root@<ip>:/srv/build-advisor/backups/
```

```bash
# server
cd /srv/build-advisor
chown deploy:deploy backups/*.dump
bash deploy/restore_db.sh backups/build_advisor-<date>.dump
```

[`restore_db.sh`](../deploy/restore_db.sh) stops the app, replaces the
database, rebuilds the search indexes (a few minutes), checks that they exist
and starts the app again. Run the same two steps whenever you've re-imported
or re-indexed locally. Your local admin account comes along; to make a new
one: `docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser`.

## 4. Start it

```bash
# server (as root): files you created as root must belong to the deploy user
chown -R deploy:deploy /srv/build-advisor
sudo -u deploy bash /srv/build-advisor/deploy/deploy.sh
```

The first build takes ~10 minutes (PyTorch, Path of Building); the first start
downloads bge-m3 (~2 GB) into a volume. Then open `https://<DOMAIN>`.

## 5. Deploy on every push (GitHub Actions)

```bash
# server: a key only for GitHub Actions
sudo -u deploy ssh-keygen -t ed25519 -N "" -f /home/deploy/.ssh/github_actions
sudo -u deploy sh -c 'cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys'
cat /home/deploy/.ssh/github_actions    # copy this private key
```

GitHub → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | the server's IP |
| `DEPLOY_SSH_KEY` | the private key printed above |

After that, every push to `main` that passes CI is deployed
([`deploy.yml`](../.github/workflows/deploy.yml)); you can also run it by hand
under Actions → Deploy.

## What survives a deploy

Deploys rebuild the app container; data lives in named Docker volumes that are
kept: `pgdata` (the database, including the daily question counter and admin
accounts), `hf_cache` (the bge-m3 download) and `caddy_data` (HTTPS
certificates). `.env.prod` and `backups/` are ignored by git, so the
`git reset` in `deploy.sh` leaves them alone. Data is only lost with
`docker compose down -v`, `docker volume rm`, deleting the server, or
restoring a dump with `--clean`.

The nightly dumps in `backups/` are on the same server. Enable Hetzner's
Backups, or copy a dump off the server now and then:
`scp root@<ip>:/srv/build-advisor/backups/nightly-Mon.dump .`

## Day to day

```bash
# server, in /srv/build-advisor
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f web    # logs
docker compose -f docker-compose.prod.yml --env-file .env.prod ps            # status
ls backups/                                                                   # nightly dumps
```

Memory on a 4 GB CX23 (measured with
[`scripts/compare_precision.py`](../scripts/compare_precision.py)): the app
~2 GB (bge-m3 in float32 adds ~1.6 GB once in use; its weights are
memory-mapped, so unused parts stay on disk), Path of Building ~0.3 GB,
Postgres ~0.3 GB, Caddy ~30 MB: about 2.6 GB, with 4 GB of swap as a safety
net. Lower-precision models don't help on this kind of CPU: bfloat16 was 8x
slower per question without saving memory, and int8 shifted the vectors
(cosine 0.95) and needed 6 GB while converting. `docker stats` shows live use.

## Keeping the wiki data current

`python manage.py refresh_wiki` asks the wiki which pages changed (in batches of
50), downloads only those plus new pages and the patch notes of the last year
("Version 3.29.3" pages), and reindexes them. `server-setup.sh` schedules it
every Monday at 04:30; on a server set up before that, add the job once:

```bash
cat > /etc/cron.d/build-advisor-refresh <<'CRON'
30 4 * * 1 deploy cd /srv/build-advisor && docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T web python manage.py refresh_wiki >> /srv/build-advisor/backups/refresh.log 2>&1
CRON
```

The output goes to `backups/refresh.log`. If the wiki's bot protection blocks
the server, the job stops without touching the index and tries again next week.
Embedding loads a second copy of the model for a few minutes (about 2 GB), which
the swap file covers on a CX23.

