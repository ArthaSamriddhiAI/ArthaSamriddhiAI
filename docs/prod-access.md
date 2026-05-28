# Prod Access — ArthaSamriddhiAI

Operational runbook for the production EC2 instance. **Canonical deploy path is `git push origin prod`** (triggers `.github/workflows/deploy-prod.yml`). Manual SSH is break-glass only.

- **Host:** `13.204.187.25`
- **User:** `ubuntu`
- **OS:** Ubuntu
- **App dir:** `/home/ubuntu/ArthaSamriddhiAI`
- **PEM (local):** `D:\Desktop\ArthaSamriddhiAI.pem`
- **SSH port:** 22

> **TODO — confirm on first SSH:** Port 80 fronting (nginx / caddy / ALB?) is not captured in the repo. Run `sudo ss -tlnp | grep :80` and `ls /etc/nginx/sites-enabled/` on the server, then update this doc with what's actually serving `http://13.204.187.25/`.

---

## 1. First-time setup (Windows 11 + PowerShell)

### 1a. Lock down PEM file permissions

Windows doesn't honour `chmod 400`. OpenSSH on Windows will refuse keys readable by anyone other than the current user ("UNPROTECTED PRIVATE KEY FILE"). Fix it with `icacls`:

```powershell
$pem = "D:\Desktop\ArthaSamriddhiAI.pem"

# Disable inheritance and drop inherited ACEs
icacls $pem /inheritance:r

# Grant only the current user Read
icacls $pem /grant:r "$($env:USERNAME):(R)"

# Remove common groups that may still have access
icacls $pem /remove "Authenticated Users" "BUILTIN\Users" "Everyone" "NT AUTHORITY\Authenticated Users"

# Verify
icacls $pem
```

Expected output: only your user listed with `(R)`.

### 1b. SSH config alias

Add to `C:\Users\anjan\.ssh\config` (create the file if it doesn't exist):

```
Host arthaprod
    HostName 13.204.187.25
    User ubuntu
    IdentityFile D:\Desktop\ArthaSamriddhiAI.pem
    IdentitiesOnly yes
```

After this, `ssh arthaprod` works from any shell.

---

## 2. Connecting

### Direct

```powershell
ssh -i D:\Desktop\ArthaSamriddhiAI.pem ubuntu@13.204.187.25
```

### Via alias (after step 1b)

```powershell
ssh arthaprod
```

### Via PowerShell wrapper (honours `$env:ARTHA_PROD_PEM`)

```powershell
.\scripts\prod-ssh.ps1              # interactive shell
.\scripts\prod-ssh.ps1 -- uptime    # run a one-shot command
```

---

## 3. Ops cheatsheet

All commands assume you're SSH'd in as `ubuntu`.

### App layout

```bash
cd /home/ubuntu/ArthaSamriddhiAI
ls -la                 # should be a git checkout on branch `prod`
git status
git log --oneline -5
cat .env               # primary env file (fallback to check: /etc/artha/.env)
```

### Web service (bare uvicorn, PID-file managed — no systemd)

| What | Command |
|------|---------|
| Health | `curl -sf http://127.0.0.1:8000/api/v1/health && echo OK` |
| PID | `cat /tmp/artha.pid` |
| Process check | `ps -fp $(cat /tmp/artha.pid)` |
| Tail logs | `tail -f /tmp/artha.log` |
| Last 200 log lines | `tail -n 200 /tmp/artha.log` |
| Listening socket | `sudo ss -tlnp \| grep 8000` |

### Manual restart (break-glass — prefer `git push origin prod`)

Mirrors `.github/workflows/deploy-prod.yml` lines 30–33:

```bash
cd /home/ubuntu/ArthaSamriddhiAI
bash -c 'kill $(cat /tmp/artha.pid 2>/dev/null) 2>/dev/null; exit 0'
sleep 3
.venv/bin/uvicorn artha.app:app --host 127.0.0.1 --port 8000 --workers 1 > /tmp/artha.log 2>&1 &
echo $! > /tmp/artha.pid
sleep 5
curl -sf http://127.0.0.1:8000/api/v1/health
```

### Daily data pipeline (systemd — installed by `scripts/setup_cron.sh`)

Runs `scripts/run_pipeline.py --all` then `scripts/refresh_cache.py` at 22:30 UTC (4 AM IST).

| What | Command |
|------|---------|
| Timer status | `systemctl status artha-pipeline.timer` |
| Next scheduled run | `systemctl list-timers artha-pipeline.timer --no-pager` |
| Last run logs | `journalctl -u artha-pipeline.service -n 200 --no-pager` |
| Follow live | `journalctl -u artha-pipeline.service -f` |
| Manual trigger | `sudo systemctl start artha-pipeline.service` |
| Service status | `systemctl status artha-pipeline.service` |

### Database

```bash
ls -lh /home/ubuntu/ArthaSamriddhiAI/artha.db
sqlite3 /home/ubuntu/ArthaSamriddhiAI/artha.db ".tables"
```

### Port 80 fronting — unresolved

See TODO at top. Until confirmed, don't assume nginx exists. Checks:

```bash
sudo ss -tlnp | grep ':80 '
ls /etc/nginx/sites-enabled/ 2>/dev/null
systemctl status nginx 2>/dev/null
systemctl status caddy 2>/dev/null
```

---

## 4. Deploy flow

### Canonical: push to `prod`

```bash
# from local, on dev branch with changes merged/ready
git checkout prod
git merge --ff-only dev    # or whatever integration policy
git push origin prod
```

GitHub Actions (`.github/workflows/deploy-prod.yml`) then:
1. SSHes to `$EC2_HOST` as `$EC2_USER` with `$EC2_SSH_KEY`
2. `git fetch && git reset --hard origin/prod` in `/home/ubuntu/ArthaSamriddhiAI`
3. `pip install -e .` into `.venv`
4. Kills old PID, relaunches uvicorn, writes new PID
5. Health check

Watch the run under the repo's **Actions** tab on GitHub.

### Break-glass: manual

Only if GHA is down or a fix can't wait for the pipeline. Use the restart block in §3.

---

## 5. Troubleshooting

### `Connection refused` / `Connection timed out`

- Wrong IP? Confirm `13.204.187.25` is still the instance's public IP (EC2 elastic IPs survive stop/start; default public IPs do not).
- Security group missing port 22 for your source IP. Check in AWS console → EC2 → Security Groups.
- `sshd` down on the server (rare). You'll need AWS Session Manager or console access to recover.

### `Permission denied (publickey)`

- Wrong user. Must be `ubuntu` on Ubuntu AMIs (not `ec2-user`, not `root`).
- Wrong key file. Confirm `-i D:\Desktop\ArthaSamriddhiAI.pem` path.
- PEM permissions too open on Windows → re-run the `icacls` block in §1a.
- Key not actually installed in `~/.ssh/authorized_keys` on the server (only fixable via AWS Session Manager or a rebuilt instance with a known key).

### `UNPROTECTED PRIVATE KEY FILE!` / `Permissions for '...' are too open`

Windows-specific ACL issue. Re-run §1a `icacls` commands.

### `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`

Two possibilities:
1. **Instance was rebuilt / replaced** (legit): remove the stale entry, then reconnect.
   ```powershell
   ssh-keygen -R 13.204.187.25
   ssh-keygen -R arthaprod
   ```
2. **Active MITM / DNS hijack** (not legit): do **not** connect. Verify via AWS console that the IP still belongs to the expected instance, and confirm the host key fingerprint out-of-band (EC2 console → Actions → Monitor and troubleshoot → Get system log → look for the `ssh-rsa`/`ssh-ed25519` fingerprint).

### `Too many authentication failures`

SSH is offering other keys before the PEM. Force `IdentitiesOnly`:
```powershell
ssh -o IdentitiesOnly=yes -i D:\Desktop\ArthaSamriddhiAI.pem ubuntu@13.204.187.25
```
The config snippet in §1b already sets this for `arthaprod`.

### App returns 502 / not reachable on `:80`

Reverse proxy (see TODO) is down or misconfigured. Confirm uvicorn itself is healthy first:
```bash
curl -sf http://127.0.0.1:8000/api/v1/health
```
If that works, the issue is in whatever fronts port 80. If it doesn't, restart via §3.
