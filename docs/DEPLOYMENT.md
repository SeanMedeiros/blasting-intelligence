# Deployment on a Site Server (HTTPS)

This guide turns one Windows computer into the site's Blasting Intelligence server, reachable from the other
workstations through `https://…`. Read [INSTALLATION.md](INSTALLATION.md) first: `setup.bat` must have run on
the server.

| What | Choice |
|---|---|
| Server | Windows 10/11 Pro or Windows Server 2016+, always on, fixed IP address or DNS name |
| Process | Scheduled task "Blasting Intelligence" (Windows Task Scheduler) running as SYSTEM or a service account; starts with Windows, restarted within 5 minutes if it stops |
| Encryption | HTTPS served by the application itself (certificate from IT, or from the site's internal CA made by `make_certificate.bat`); optional plain-HTTP port that redirects to HTTPS |
| Settings | `server.env` in the application folder (template: `server.env.example`) |
| Logs | `data\logs\server.log` (application) and `access.log` (requests), rotated daily, 90 days kept |

No third-party service wrapper or web server is needed. A company reverse proxy (IIS, nginx) can be used
instead of the built-in HTTPS — see §6.

## 1. Choose the address

Agree with IT on the name users will type, e.g. `blasting.mine.local`, and ask for a DNS record pointing to the
server's fixed IP address. Without DNS, users can use the IP address (`https://10.20.1.15`) — the certificate
must then contain that IP.

## 2. Certificate

**A. Certificate issued by IT (recommended where a company PKI exists).** Ask for a server certificate for
the chosen name (and IP if used), exported as `.pfx` with its private key. Then, in the application folder:

```bat
.venv\Scripts\activate
cd backend
python -m app.manage import-pfx C:\path\blasting.pfx
```

The workstations already trust the company CA: nothing to install on them.

**B. Site internal CA (no company PKI).**

```bat
make_certificate.bat --dns blasting.mine.local --ip 10.20.1.15
```

This creates, in `data\tls\`:
- `ca.crt` / `ca.key` — the site's certificate authority (10 years, created the first time only);
- `server.crt` / `server.key` — the server certificate (1 year; browsers refuse more than 397 days).

Install `ca.crt` as a **trusted root** on every workstation:
- one workstation: copy `ca.crt` and `deploy\windows\trust-ca.bat`, run `trust-ca.bat ca.crt` as Administrator;
- many workstations (domain): Group Policy → *Computer Configuration → Policies → Windows Settings → Security
  Settings → Public Key Policies → Trusted Root Certification Authorities* → Import `ca.crt`.

Then **move `ca.key` off the server** (e.g. to a USB key in the safe). It is only needed to renew the
certificate next year; `make_certificate.bat` refuses to make a new CA while `ca.crt` exists without its key,
so the workstations never have to be re-configured by accident.

Check a certificate at any time: `python -m app.manage cert-info` (names, expiry).

## 3. Settings — `server.env`

Copy `server.env.example` to `server.env` and edit it. Minimal HTTPS configuration:

```ini
BI_HOST=0.0.0.0
BI_PORT=443
BI_PUBLIC_URL=https://blasting.mine.local
BI_TLS_CERT=C:\BlastingIntelligence\data\tls\server.crt
BI_TLS_KEY=C:\BlastingIntelligence\data\tls\server.key
BI_HTTP_REDIRECT_PORT=80
BI_DEFAULT_LANGUAGE=fr
```

| Variable | Default | Purpose |
|---|---|---|
| `BI_HOST` | `127.0.0.1` | Interface listened on. `0.0.0.0` = the network. |
| `BI_PORT` | 8000 (demo 8001) | Port; 443 for HTTPS without a port number in the address |
| `BI_TLS_CERT` / `BI_TLS_KEY` | — | PEM certificate (with chain) and key → HTTPS. `BI_TLS_KEY_PASSWORD` if the key is encrypted |
| `BI_HTTP_REDIRECT_PORT` | 0 | Plain-HTTP port answering only with a redirect to HTTPS (e.g. 80) |
| `BI_PUBLIC_URL` | — | Address users type; used in redirects, checks and the Settings card |
| `BI_ALLOWED_HOSTS` | — | Other names/IPs that reach the server (its own names and IPs are always accepted); `*` disables the check |
| `BI_TRUSTED_PROXIES` | — | Reverse-proxy address(es) whose `X-Forwarded-*` headers are trusted (§6) |
| `BI_COOKIE_SECURE` | automatic | Session cookie sent over HTTPS only — automatic with built-in HTTPS; set `1` behind an HTTPS proxy |
| `BI_LOG_DIR` | `data\logs` | Log folder |

Windows environment variables override `server.env`. Check without starting:
`cd backend` then `python -m app.serve --check`.

## 4. Install the background server

Right-click **`install_service.bat` → Run as administrator**. It:
1. checks `server.env` and the certificate (refuses to install with a missing or mismatched key, an expired
   certificate, or contradictory settings), and asks for confirmation if the server would be on the network
   without HTTPS;
2. applies database migrations (backup first);
3. registers the scheduled task (at start-up + a check every 5 minutes that starts it again if it stopped);
4. restricts `data\tls` to Administrators, SYSTEM and the service account;
5. opens the firewall for the port(s) on the **Domain and Private** profiles only;
6. starts the server and waits until `/api/health` answers.

To run under a dedicated domain account instead of SYSTEM (recommended when `BI_BACKUP_DIR` is a network
share): `install_service.bat -Account MINE\svc-blasting` (the account needs *Log on as a batch job* and
modify rights on the application folder and the backup share).

| Task | Command |
|---|---|
| Status (task, answer on `/api/health`) | `service_status.bat` |
| Restart after editing `server.env` or renewing the certificate | `service_status.bat restart` (as Administrator; refused if the new settings are invalid) |
| Remove (data, backups and certificates kept) | `uninstall_service.bat` (as Administrator) |
| Update to a new version | `uninstall_service.bat` → replace the application files (keep `data\` and `server.env`) → `setup.bat` → `install_service.bat` |

`start.bat` still runs the same server in a console window (useful for a first test); do not run both at the same time.

## 5. What protects the server

| Measure | Detail |
|---|---|
| HTTPS | TLS 1.2+ (Python defaults); HSTS 180 days on HTTPS responses; HTTP port only redirects (308) |
| Session cookie | HttpOnly, SameSite=Strict, Secure with HTTPS; 12 h maximum, 2 h idle |
| Cross-site requests | Writes need the `X-Requested-With` header and, when the browser sends an Origin, the same origin |
| Host check | Requests for unknown host names are refused (DNS-rebinding protection) |
| Security headers | Content-Security-Policy (own scripts only, no framing), `nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy` |
| Sign-in | Account lock after 5 failures (15 min); generic error message |
| Firewall | Only the application port(s), Domain and Private profiles |
| Certificate expiry | Alert on the dashboard 30 days before (critical at 7), warning in the log at start, shown in Settings |
| Health probe | `GET /api/health` — 200 `{"status":"ok"}` or 503 if the database does not answer; no sign-in, no data (for IT monitoring) |

## 6. Behind a company reverse proxy (alternative)

If IT publishes internal applications through IIS (ARR) or nginx, let the proxy do HTTPS and keep the
application on the server itself:

```ini
BI_HOST=127.0.0.1
BI_PORT=8000
BI_TRUSTED_PROXIES=127.0.0.1
BI_COOKIE_SECURE=1
BI_PUBLIC_URL=https://blasting.mine.local
```

The proxy must forward the original `Host` header and `X-Forwarded-Proto`, allow uploads of 210 MB (point clouds
are limited to 200 MB) and timeouts of 300 s. Example for nginx: `deploy/linux/nginx-reverse-proxy.conf`.

## 7. Linux server (optional)

The application runs the same way on Linux: `python -m app.serve` with the same `server.env`. A hardened
systemd unit is provided in `deploy/linux/blasting-intelligence.service` (dedicated user, read-only system,
writes limited to `data/`, no restart loop on invalid settings). Certificate commands are identical
(`python -m app.manage make-cert …`).

## 8. Acceptance check after installation

1. From a workstation: open the public address — padlock shown, no certificate warning.
2. `http://blasting.mine.local` → redirected to `https://…`.
3. Sign in, open **Settings → Server, database & backups**: *HTTPS*, certificate validity, accepted names.
4. Restart the server computer: the application answers again without anyone signing in.
5. Run the end-to-end check from a workstation with Python: `python e2e/production_smoke.py https://blasting.mine.local`
   (on an empty production database only) or `python e2e/smoke.py` against a demonstration server.
