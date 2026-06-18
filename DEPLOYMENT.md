# Server 1 Deployment

Voice Message Studio runs behind Nginx the same way Mailcheck does: the container
binds to localhost, and Nginx owns the public domain.

- Public host: `voice.basisvps.com`
- Local app port: `127.0.0.1:8011`
- Repo path on the server: `~/voice-studio`

## First-time deploy

```bash
cd ~/voice-studio
git pull --ff-only origin main

ELEVENLABS_API_KEY='replace-with-elevenlabs-key'
HUGGINGFACE_TOKEN='replace-with-huggingface-token'   # required for OmniVoice

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

# OmniVoice (Hugging Face Space). HUGGINGFACE_TOKEN is required to generate.
HUGGINGFACE_TOKEN=${HUGGINGFACE_TOKEN}
OMNIVOICE_BASE_URL=https://salmanbvps-omnivoice-batch-tts.hf.space
OMNIVOICE_TIMEOUT_SECONDS=240
OMNIVOICE_BATCH_CHUNK=6

# Optional: set to enable X-API-Key access for Swagger / machine clients.
# API_KEY=

DATA_DIR=/app/data
STATIC_DIR=/app/frontend_dist
EOF

chmod 600 .env
docker compose up -d --build
curl -s http://127.0.0.1:8011/api/health
```

## Updating an existing deployment

```bash
cd ~/voice-studio
git pull --ff-only origin main
docker compose down            # stop old container (bind-mounted ./data is preserved)

# One-time: move pre-Phase-1 data into the per-provider subtree. Idempotent.
cd data
if [ -d voices ] || [ -d jobs ] || [ -d source_audio ]; then
  mkdir -p elevenlabs
  for d in voices jobs source_audio generated_audio batches; do
    [ -e "$d" ] && mv "$d" "elevenlabs/$d"
  done
  echo "migrated existing data -> data/elevenlabs/"
fi
cd ..

# If .env predates OmniVoice, add the OmniVoice settings (keep existing lines):
#   HUGGINGFACE_TOKEN=...        (required for OmniVoice)
#   OMNIVOICE_BASE_URL=https://salmanbvps-omnivoice-batch-tts.hf.space
#   OMNIVOICE_TIMEOUT_SECONDS=240
#   OMNIVOICE_BATCH_CHUNK=6

docker compose up -d --build
```

## Verify

```bash
curl -s http://127.0.0.1:8011/api/health
# {"status":"ok","auth_mode":"google","providers":{"elevenlabs":true,"omnivoice":true},"ffmpeg_available":true}
docker compose ps                     # Up (healthy)
docker compose logs --tail=30 app
```

Health only confirms config is present, not that secrets are valid. Confirm the
real paths in a browser through the proxy:

- `https://voice.basisvps.com/elevenlabs/voices` and `/elevenlabs/history` —
  existing voices and jobs are present (i.e. the data migration ran).
- `https://voice.basisvps.com/omnivoice/generate` — pick the **English – American**
  design preset and generate; audio confirms `HUGGINGFACE_TOKEN` works.

`./data` is the source of truth (voices, OmniVoice speech contexts, and jobs) and
persists across `up --build`. Interactive API docs: `https://voice.basisvps.com/docs`.

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
