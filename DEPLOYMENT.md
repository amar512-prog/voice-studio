# Server 1 Deployment

Voice Message Studio should run behind Nginx the same way Mailcheck does: the
container binds to localhost, and Nginx owns the public domain.

Assumed public host:

- `voice.basisvps.com`

Assumed local app port:

- `127.0.0.1:8011`

## App

```bash
cd ~/text_to_speech
git pull --ff-only origin main

ELEVENLABS_API_KEY='replace-with-elevenlabs-key'

cat > .env <<EOF
AUTH_MODE=google
GOOGLE_CLIENT_ID=494988980977-7eo69ts0lnl3vf1ejt2p7mkq215un9bf.apps.googleusercontent.com
GOOGLE_ALLOWED_DOMAINS=basisvps.com
HOST_BIND=127.0.0.1
HOST_PORT=8011
SESSION_SECRET=$(openssl rand -hex 32)
SESSION_SECURE=true
ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY}
ELEVENLABS_MODEL_ID=eleven_v3
ELEVENLABS_LANGUAGE_CODE=en
DATA_DIR=/app/data
STATIC_DIR=/app/frontend_dist
EOF

chmod 600 .env
docker compose up -d --build
curl -s http://127.0.0.1:8011/health
```

## Nginx

```bash
cat > /etc/nginx/sites-available/voice-studio <<'EOF'
server {
    listen 80;
    server_name voice.basisvps.com;
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8011;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -s /etc/nginx/sites-available/voice-studio /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

If HTTPS is not already provisioned for the subdomain, run the same Certbot flow
used for `mailcheck.basisvps.com`, then keep `SESSION_SECURE=true`.
