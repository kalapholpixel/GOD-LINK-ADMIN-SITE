# PROPERTY-SALES-ADMIN

This repository hosts an admin editor plus API endpoints that serve content to a separate client website on a different domain.

Source of truth is `data/data.json`.

## Local Run

```bash
python3 server.py
```

Open `http://localhost:3000`.

## Production Environment Variables

Set these on the admin/API host:

- `PORT`
	- Server port (default `3000`).
- `ALLOWED_READ_ORIGINS`
	- Comma-separated origins allowed to call `GET /api/data` and `GET /api/events`.
	- Example: `https://client.example.com,https://admin.example.com`
- `ALLOWED_SAVE_ORIGINS`
	- Comma-separated origins allowed to call `POST /save`.
	- Example: `https://admin.example.com`
- `SAVE_API_KEY`
	- Optional key required by `POST /save` via `X-Admin-Key` header.
- `SSE_RETRY_MS`
	- Optional EventSource reconnect hint in milliseconds (default `3000`).
- `CORS_DENY_BY_DEFAULT`
	- Optional strict mode (`true`/`false`, default `false`).
	- When `true`, requests with `Origin` header are rejected unless the origin is explicitly listed in the relevant allowlist.

If `ALLOWED_READ_ORIGINS` or `ALLOWED_SAVE_ORIGINS` are not set, that endpoint group allows all origins (development-friendly, less secure).

## API Contract

- `GET /api/data`
	- Returns latest JSON from `data/data.json`.
	- Sends anti-cache headers so client always gets fresh content.

- `GET /api/events`
	- SSE stream for near real-time updates.
	- Emits event: `content-updated`
	- Event payload:
		- `{ "version": number, "updatedAt": unixTimestamp }`

- `POST /save`
	- Accepts JSON body.
	- Atomically writes `data/data.json`.
	- If `SAVE_API_KEY` is set, requires header: `X-Admin-Key`.
	- Response:
		- `{ "ok": true, "version": number, "updatedAt": unixTimestamp }`

- `POST /api/auth/verify`
	- Verifies admin key without writing data.
	- Uses same CORS/auth policy as `POST /save`.
	- Response:
		- `{ "ok": true, "authRequired": false }` when key is not required.
		- `{ "ok": true, "authRequired": true }` when valid key is supplied.

## Admin UI to API Connection

The admin page supports runtime config with `window.GODLINK_ADMIN_CONFIG`:

```html
<script>
	window.GODLINK_ADMIN_CONFIG = {
		apiBase: "https://admin-api.example.com",
		adminKey: "replace-if-you-use-save-api-key"
	};
</script>
```

Quick test option:

- `?apiBase=https://admin-api.example.com`
- `?adminKey=your-key`

These values are persisted in `localStorage` (`godlink_api_base`, `godlink_admin_key`).

When `SAVE_API_KEY` is configured, the admin page now performs a verification call to `POST /api/auth/verify` and prompts for key entry if needed, then stores the validated key in local storage.

## Client Site Connection (Different Domain)

In client app:

1. Fetch initial data from `https://admin-api.example.com/api/data`.
2. Open `EventSource` to `https://admin-api.example.com/api/events`.
3. On each `content-updated`, re-fetch data and update UI.
4. Keep a polling fallback in case SSE is blocked by network/proxy.

Example:

```js
const ADMIN_API = "https://admin-api.example.com";
let pollTimer = null;

async function fetchContent() {
	const res = await fetch(`${ADMIN_API}/api/data`, { cache: "no-store" });
	if (!res.ok) throw new Error("Content fetch failed");
	return res.json();
}

async function refreshContent() {
	const data = await fetchContent();
	applyContent(data);
}

function startPollingFallback() {
	if (pollTimer) return;
	pollTimer = setInterval(() => {
		refreshContent().catch(() => {});
	}, 8000);
}

function connectEvents() {
	const events = new EventSource(`${ADMIN_API}/api/events`);
	events.addEventListener("content-updated", () => {
		refreshContent().catch(() => {});
	});
	events.onerror = () => {
		events.close();
		startPollingFallback();
		setTimeout(connectEvents, 4000);
	};
}

refreshContent().then(connectEvents).catch(startPollingFallback);
```

## Reverse Proxy Notes (Nginx)

For SSE route, disable buffering and increase timeouts:

```nginx
location /api/events {
	proxy_pass http://127.0.0.1:3000;
	proxy_http_version 1.1;
	proxy_set_header Connection "";
	proxy_buffering off;
	proxy_cache off;
	proxy_read_timeout 3600;
	add_header X-Accel-Buffering no;
}

location / {
	proxy_pass http://127.0.0.1:3000;
	proxy_http_version 1.1;
}
```

## Security Recommendations

- Use HTTPS on both domains.
- Set explicit origin allowlists for read and save endpoints.
- Turn on `CORS_DENY_BY_DEFAULT=true` in production.
- Restrict save to admin domain only.
- Enable `SAVE_API_KEY` (or stronger auth) before production.
- Do not use wildcard origin settings in production unless truly required.

## Deployment Assets Included

This repo now includes ready-to-use deployment templates:

- `.env.example`
	- Environment variable template for cross-domain production setup.
- `deploy/god-link-admin.service`
	- Systemd unit template for running `server.py` as a managed service.
- `deploy/nginx-admin-api.conf`
	- Nginx reverse proxy template with SSE-friendly settings.
- `deploy/nginx-admin-api-https.conf`
	- HTTPS-first Nginx template with admin-page Basic Auth and public read endpoints for client consumption.

## Quick Linux Deployment (Systemd + Nginx)

1. Copy project to server:

```bash
sudo mkdir -p /var/www
sudo cp -R ./GOD-LINK-ADMIN-SITE /var/www/GOD-LINK-ADMIN-SITE
cd /var/www/GOD-LINK-ADMIN-SITE
```

2. Create production env file:

```bash
cp .env.example .env
# then edit .env values for your real domains and secret
```

3. Install and start systemd service:

```bash
sudo cp deploy/god-link-admin.service /etc/systemd/system/god-link-admin.service
sudo systemctl daemon-reload
sudo systemctl enable god-link-admin
sudo systemctl start god-link-admin
sudo systemctl status god-link-admin
```

4. Install and enable Nginx site:

```bash
sudo cp deploy/nginx-admin-api.conf /etc/nginx/sites-available/admin-api.conf
sudo ln -sf /etc/nginx/sites-available/admin-api.conf /etc/nginx/sites-enabled/admin-api.conf
sudo nginx -t
sudo systemctl reload nginx
```

Optional hardened Nginx setup (recommended): use HTTPS + Basic Auth template.

```bash
sudo apt-get install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd-admin <admin-username>
sudo cp deploy/nginx-admin-api-https.conf /etc/nginx/sites-available/admin-api.conf
sudo ln -sf /etc/nginx/sites-available/admin-api.conf /etc/nginx/sites-enabled/admin-api.conf
sudo nginx -t
sudo systemctl reload nginx
```

5. Add TLS certificate (recommended):

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d admin-api.example.com
```

## Post-Deploy Checks

```bash
# Replace origins and host with your real domains
curl -i https://admin-api.example.com/api/data -H 'Origin: https://client.example.com'
curl -i -X POST https://admin-api.example.com/api/auth/verify \
	-H 'Origin: https://admin.example.com' \
	-H 'X-Admin-Key: YOUR_KEY' \
	-H 'Content-Type: application/json' \
	-d '{}'
curl -N https://admin-api.example.com/api/events -H 'Origin: https://client.example.com'
```

## Hostinger Deployment Guide

If you are hosting the admin API on Hostinger, use a VPS plan (recommended). This project needs a long-running Python process (`server.py`), which is not a good fit for typical shared hosting.

### Architecture (Different Domains)

- Admin/API domain: `admin-api.yourdomain.com` (Hostinger VPS)
- Client domain: `www.yourclientdomain.com` (any host)

Set:

- `ALLOWED_READ_ORIGINS=https://www.yourclientdomain.com,https://admin-api.yourdomain.com`
- `ALLOWED_SAVE_ORIGINS=https://admin-api.yourdomain.com`
- `CORS_DENY_BY_DEFAULT=true`
- `SAVE_API_KEY=<strong-random-secret>`

### 1. Create Hostinger VPS

In Hostinger hPanel:

1. Create VPS (Ubuntu 24.04 recommended).
2. Note server IP, root user access, and SSH credentials.

### 2. Point DNS to VPS

In your DNS zone:

1. Create `A` record:
	 - Host: `admin-api`
	 - Value: `<your-vps-ip>`
2. Wait for DNS propagation.

### 3. SSH and Install Dependencies

```bash
ssh root@<your-vps-ip>
apt-get update
apt-get install -y python3 nginx certbot python3-certbot-nginx git
```

### 4. Deploy Project

```bash
mkdir -p /var/www
cd /var/www
git clone https://github.com/kalapholpixel/GOD-LINK-ADMIN-SITE.git
cd GOD-LINK-ADMIN-SITE
cp .env.example .env
```

Edit `.env` with your real domains and secret.

### 5. Configure Systemd

```bash
cp deploy/god-link-admin.service /etc/systemd/system/god-link-admin.service
systemctl daemon-reload
systemctl enable god-link-admin
systemctl start god-link-admin
systemctl status god-link-admin
```

### 6. Configure Nginx

```bash
cp deploy/nginx-admin-api.conf /etc/nginx/sites-available/admin-api.conf
ln -sf /etc/nginx/sites-available/admin-api.conf /etc/nginx/sites-enabled/admin-api.conf
nginx -t
systemctl reload nginx
```

For stronger admin protection, use `deploy/nginx-admin-api-https.conf` instead of `deploy/nginx-admin-api.conf`.
It adds:

- HTTP to HTTPS redirect.
- Basic Auth for admin UI and write endpoints.
- Public access only for `/api/data` and `/api/events` (required by cross-domain client site).

Before SSL, update `server_name` in `deploy/nginx-admin-api.conf` (or directly in `/etc/nginx/sites-available/admin-api.conf`) to your real host:

- `server_name admin-api.yourdomain.com;`

### 7. Enable HTTPS (Let's Encrypt)

```bash
certbot --nginx -d admin-api.yourdomain.com
```

### 8. Verify Production Endpoints

```bash
curl -i https://admin-api.yourdomain.com/api/data -H 'Origin: https://www.yourclientdomain.com'
curl -i -X POST https://admin-api.yourdomain.com/api/auth/verify \
	-H 'Origin: https://admin-api.yourdomain.com' \
	-H 'X-Admin-Key: <your-secret>' \
	-H 'Content-Type: application/json' \
	-d '{}'
curl -N https://admin-api.yourdomain.com/api/events -H 'Origin: https://www.yourclientdomain.com'
```

### 9. Run Admin UI Against Hosted API

Open the admin page with:

- `https://admin-api.yourdomain.com/?apiBase=https://admin-api.yourdomain.com`

Optional first-time key shortcut:

- `https://admin-api.yourdomain.com/?apiBase=https://admin-api.yourdomain.com&adminKey=<your-secret>`

After first load, values are persisted in local storage.

### Hostinger Shared Hosting Note

If you only have Hostinger shared hosting (no VPS), host the client site there if needed, but run this admin API on a VPS/provider that supports persistent Python services.