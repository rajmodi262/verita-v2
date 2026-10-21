# Deploy on Oracle Cloud (Always Free, ARM)

One Ampere A1 VM (aarch64) running the compose stack behind Caddy, as ADR-008 describes. The
released images are amd64-only, so this VM **builds the images itself** with
`deploy/prod/docker-compose.selfbuild.yml`. CI job `images-arm64` builds both images natively on
ARM on every change, so the build is known to work before you start.

You need: an Oracle Cloud account, a build machine that already has the repo, `uv` and the data
(it produces `demo-pack/`), and about an hour.

## 1. Create the VM

1. *Compute → Instances → Create instance.* Image **Canonical Ubuntu 24.04**; shape
   **VM.Standard.A1.Flex** (Ampere). Always Free covers up to 4 OCPU and 24 GB in total; use
   **2 OCPU / 12 GB** or more, because building the API image is the heaviest step.
2. Add your SSH public key, keep the public IPv4 address, and create it.
3. **"Out of host capacity"** is common for A1 in busy regions. Retry later, try another
   availability domain, or start with fewer OCPUs and resize afterwards.

## 2. Open ports 80 and 443, in two places

Both are needed. Oracle's Ubuntu images ship with a restrictive iptables policy, so opening only
the security list is not enough.

1. **VCN security list:** *Networking → Virtual cloud networks → your VCN → Security lists →
   Default → Add ingress rules*: source `0.0.0.0/0`, TCP, destination ports `80` and `443`.
2. **On the VM:**

   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```

## 3. Install Docker and get the code

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker
git clone https://github.com/rajmodi262/verita-v2.git && cd verita-v2
```

From the **build machine**, copy the demo pack (about 40 MB; it is not in git):

```bash
scp -r demo-pack ubuntu@<VM_IP>:~/verita-v2/
```

## 4. Signing key

```bash
mkdir -p keys
openssl genpkey -algorithm ed25519 -out keys/verita-signing.pem
sudo chown 10001:10001 keys/verita-signing.pem   # the containers run as uid 10001
sudo chmod 600 keys/verita-signing.pem
```

This is a PKCS#8 PEM Ed25519 key, the format `Signer.load_or_create`
(`backend/verita/defend/signing.py`) loads. The API publishes the matching public key at
`GET /api/v1/keys`. Offline verifiers (`verita-verify --pubkey`) need **that** key, not the
`keys/verita-pub.pem` in git, which belongs to the development key. Back the private key up
somewhere safe. If you lose it, rotate it as RUNBOOK.md describes.

## 5. Domain and environment

1. Get a free domain at [duckdns.org](https://www.duckdns.org): sign in, create a subdomain, and
   set its IP to the VM's public IPv4. Caddy obtains the HTTPS certificate on first start; this
   needs ports 80 and 443 open (step 2).
2. Fill `deploy/prod/.env`:

   ```bash
   cp deploy/prod/.env.example deploy/prod/.env
   openssl rand -base64 24   # run twice: POSTGRES_PASSWORD, VERITA_APP_DB_PASSWORD
   nano deploy/prod/.env
   ```

   Set `VERITA_DOMAIN=<name>.duckdns.org` and the two passwords. `VERITA_REGISTRY` and
   `VERITA_TAG` are not used by the self-build override. The LLM key pools are optional: left
   empty, narratives are drafted offline from templates.

## 6. Build and start

```bash
docker compose --env-file deploy/prod/.env -f deploy/docker-compose.yml \
  -f deploy/prod/docker-compose.selfbuild.yml up -d --build
docker compose --env-file deploy/prod/.env -f deploy/docker-compose.yml \
  -f deploy/prod/docker-compose.selfbuild.yml run --rm api verita users seed-demo
```

The first build takes several minutes on ARM. `seed-demo` prints the demo users' password
**once**, so save it.

## 7. Smoke test, from your PC

```bash
cd backend
VERITA_DEMO_PASSWORD=<printed password> uv run python scripts/smoke.py https://<name>.duckdns.org
```

## Keeping it alive

* **Idle reclamation:** Oracle may reclaim Always Free instances that stay idle for 7 days (low
  CPU, network and memory use). Upgrading the account to Pay As You Go keeps Always Free
  resources free and exempts them from reclamation. Otherwise, use the demo regularly.
* **Updates:** `git pull`, then rerun the `up -d --build` command from step 6.
* Operating, backups and key rotation: [RUNBOOK.md](RUNBOOK.md).
