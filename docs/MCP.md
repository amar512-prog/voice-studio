# Voice Studio MCP server

Voice Message Studio exposes its text-to-speech workflow as an **MCP server** so
coding agents — Claude Code (CLI **and** the claude.ai web app) and Codex — can
generate voice notes directly, without a browser or any local install.

- **Endpoint:** `https://voice-notes.revengineer.ai/mcp` (streamable-HTTP)
- **Auth:** OAuth 2.0 (PKCE + Dynamic Client Registration). You sign in **once**
  with Google; the client stores a refresh token and never prompts again.
- **No local Python / API key** is needed on any client — the server is hosted
  as part of the studio app, and all clients point at the one URL.

## Tools

| Tool | What it does |
|---|---|
| `list_voices(provider="elevenlabs")` | Saved voices for a provider → `voice_id`, `display_name`, `accent`, `source_type` |
| `list_speech_contexts(provider="elevenlabs")` | Delivery styles (ElevenLabs built-ins) or saved OmniVoice speech-context ids |
| `generate_voice_note(text, voice_id, provider="elevenlabs", speech_context=..., enhance_text=False, target_seconds=55, wpm=135, export_m4a=True)` | Synthesize one note → result + `mp3_path` / `m4a_path` / URLs (the easy one-shot) |
| `generate_batch(items, provider="elevenlabs")` | Submit many notes as one async job → `job_id`; poll `get_job`, then pull audio |
| `list_jobs(provider="elevenlabs", limit=50)` | Past generation jobs, newest first |
| `get_job(job_id, provider="elevenlabs")` | Full job manifest with per-row results and local file paths |
| `get_job_audio(job_id, index=1, fmt="mp3", provider="elevenlabs")` | One row's audio as base64 over MCP (decode + write to a file) |
| `save_job_audio(job_id, out_dir, provider="elevenlabs")` | Copy a job's MP3/M4A/transcript files into a directory **on the server** |

Providers are `elevenlabs` (default) and `omnivoice`. For OmniVoice,
`speech_context` is a **required** saved context id (e.g. `english_american`);
for ElevenLabs it is an optional built-in delivery style.

`generate_voice_note` returns 200-style success even when a row fails — check
`status` (`completed` / `failed`) and read `error` on failure.

## Connect a client

The first connection opens a Google sign-in in your browser; after that it is
silent (a stored refresh token is reused, and survives redeploys).

### Claude Code — web app (claude.ai)

Settings → **Connectors** → **Add custom connector** → paste
`https://voice-notes.revengineer.ai/mcp` → complete the Google consent once.

### Claude Code — CLI

```bash
claude mcp add --transport http voicestudio https://voice-notes.revengineer.ai/mcp
```

Then, in a session, run `/mcp` and choose **Authenticate** the first time.

### Codex

Add a remote MCP server to `~/.codex/config.toml` and authenticate once:

```toml
[mcp_servers.voicestudio]
url = "https://voice-notes.revengineer.ai/mcp"
```

```bash
codex mcp login voicestudio
```

> Requires a Codex version with remote (streamable-HTTP) MCP + OAuth support. If
> your build only supports stdio MCP servers, upgrade Codex.

## Try it

Ask the agent:

> Using voicestudio, list my ElevenLabs voices, then generate a 30-second voice
> note that says "Hey Priya, quick one about your outbound hiring" with the first
> voice, and save the audio to ~/Desktop.

The agent calls `list_voices`, `generate_voice_note`, then `save_job_audio`.

## Server configuration (operators)

The MCP server is part of the studio app; no separate process. Relevant env
vars (in addition to the app's usual settings):

| Var | Default | Purpose |
|---|---|---|
| `MCP_PUBLIC_URL` | `https://voice-notes.revengineer.ai` | Public base URL; used to build the OAuth issuer + resource identifiers and discovery documents. **Must match how clients reach the server.** |
| `MCP_DISABLE_AUTH` | *(unset)* | Set to `1` to serve `/mcp` without OAuth — **local testing only**. |

OAuth clients, authorization codes, and access/refresh tokens are persisted in a
small SQLite database (`mcp_oauth.db` under `DATA_DIR`) so tokens survive
restarts. The login step reuses the app's existing Google sign-in
(`GOOGLE_CLIENT_ID`, `GOOGLE_ALLOWED_DOMAINS`); in `AUTH_MODE=development` the
authorize step auto-completes as the local developer.

Discovery + endpoints served at the site root:
`/.well-known/oauth-authorization-server`,
`/.well-known/oauth-protected-resource/mcp`, `/authorize`, `/token`,
`/register`, `/revoke`, and the MCP endpoint `/mcp`.

Requires Python **3.10+** (the deployed image is 3.12); `mcp[cli]` is pinned in
`requirements.txt`.
