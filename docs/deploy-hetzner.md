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

The 27k chunks with their embeddings come from your local database.

```powershell
# local (PowerShell): dump inside the container, then copy the file out
docker compose exec -T db pg_dump -U build_advisor -Fc -f /tmp/build_advisor.dump build_advisor
docker compose cp db:/tmp/build_advisor.dump .\build_advisor.dump
scp .\build_advisor.dump root@<ip>:/srv/build-advisor/backups/
```

```bash
# server
cd /srv/build-advisor
chown deploy:deploy backups/build_advisor.dump
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d db
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_restore -U build_advisor -d build_advisor --no-owner --clean --if-exists /backups/build_advisor.dump
```

(`--clean` drops existing tables first, so you can repeat this after
re-indexing locally.) Your local admin account comes along; to make a new one:
`docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser`.

## 4. Start it

```bash
# server
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
