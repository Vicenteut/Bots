# Sol Dashboard Access

Sol's dashboard is exposed through Cloudflare Access at:

```text
https://sol.theclamletter.com
```

The dashboard must remain private. Do not expose port `8502` directly to the
Internet.

## Login Flow

1. Open `https://sol.theclamletter.com`.
2. Complete Cloudflare Access with the allowlisted email.
3. Log in to the internal Sol dashboard with the dashboard username and password.

Store the internal dashboard password in a password manager. The repository and
`.env` files should only store `DASHBOARD_PASSWORD_HASH`, never the plaintext
password.

## Current Architecture

```text
Browser / phone
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> cloudflared on VPS
  -> http://127.0.0.1:8502
  -> sol-dashboard.service
```

`sol-dashboard.service` should listen only on `127.0.0.1:8502`. Cloudflare
Tunnel is the public entry point.

## VPS Checks

Run these on the VPS:

```bash
systemctl is-active cloudflared sol-dashboard.service sol-commands.service xbot-monitor.service nginx.service
systemctl is-enabled cloudflared sol-dashboard.service sol-commands.service xbot-monitor.service nginx.service
ss -ltnp | grep -E ':8502|cloudflared|uvicorn'
```

Expected:

```text
cloudflared: active and enabled
sol-dashboard.service: active and enabled
sol-commands.service: active and enabled
xbot-monitor.service: active and enabled
nginx.service: active and enabled
uvicorn listening on 127.0.0.1:8502 only
```

## Public Access Check

From any machine that is not already authenticated in Cloudflare Access:

```bash
curl -I https://sol.theclamletter.com
```

Expected response:

```text
HTTP/2 302
location: https://<team-name>.cloudflareaccess.com/...
www-authenticate: Cloudflare-Access ...
```

If the response goes directly to the Sol login page without a Cloudflare Access
redirect, the Access application policy is not protecting the hostname.

## Cloudflare Settings

Tunnel:

```text
Name: sol-dashboard
Public hostname: sol.theclamletter.com
Service: http://127.0.0.1:8502
```

Access application:

```text
Type: Self-hosted
Hostname: sol.theclamletter.com
Policy: Allow only approved email addresses
```

## Recovery

If Cloudflare Access or Tunnel fails, use the SSH fallback:

```bash
ssh -i /tmp/codex_xbot_ed25519 -p 443 -L 8502:127.0.0.1:8502 root@89.167.109.62
```

Then open:

```text
http://127.0.0.1:8502
```

## Useful Logs

```bash
journalctl -u cloudflared -n 100 --no-pager
journalctl -u sol-dashboard.service -n 100 --no-pager
```

## Security Notes

- Keep `sol-dashboard.service` bound to `127.0.0.1`, not `0.0.0.0`.
- Keep Cloudflare Access enabled for `sol.theclamletter.com`.
- Keep the internal dashboard password strong.
- Rotate the Cloudflare tunnel token if it is ever exposed.
- Do not commit `.env` or plaintext dashboard credentials.
