import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertCircle,
  ArrowDownWideNarrow,
  CheckCircle2,
  Copy,
  Download,
  FileSpreadsheet,
  LogOut,
  Mic,
  Pause,
  Play,
  Plus,
  RefreshCcw,
  Save,
  Trash2,
  Upload,
  Volume2,
  Wand2
} from "lucide-react";
import "./styles.css";

const DEFAULT_CONTEXTS = [
  {
    id: "outreach_conversational",
    label: "Outreach conversational",
    note: "Warm, natural, concise, one-to-one delivery."
  },
  { id: "customer_support", label: "Customer support", note: "Calm and reassuring." },
  { id: "narration", label: "Narration", note: "Steady explanatory pacing." },
  { id: "announcement", label: "Announcement", note: "Confident and clear." },
  { id: "character_dialogue", label: "Character dialogue", note: "Expressive character voice." },
  { id: "dramatic_storytelling", label: "Dramatic storytelling", note: "Emotional and deliberate." }
];

const DEFAULT_ACCENTS = [
  { id: "us", label: "American" },
  { id: "in", label: "Indian" },
  { id: "neutral", label: "Neutral" }
];

const ACCENT_LABELS = {
  us: "American",
  in: "Indian",
  neutral: "Neutral"
};

const PROVIDER_ACCENT_OPTIONS = [
  { id: "us", label: "American" },
  { id: "in", label: "Indian" }
];

const PROVIDER_SORTS = [
  { id: "trending", label: "Trending" },
  { id: "latest", label: "Latest" },
  { id: "most_users", label: "Most users" },
  { id: "characters", label: "Characters" }
];
const PROVIDERS = [
  {
    id: "elevenlabs",
    label: "ElevenLabs",
    shortLabel: "EL",
    modelLabel: "Eleven v3 Natural",
    subtitle: "Library voices, shared voices, and hosted cloning.",
    supportsVoiceLibrary: true,
    supportsRawVoiceId: true
  },
  {
    id: "omnivoice",
    label: "OmniVoice",
    shortLabel: "OV",
    modelLabel: "OmniVoice Batch",
    subtitle: "Local presets and sample-based clones through the Hugging Face Space.",
    supportsVoiceLibrary: false,
    supportsRawVoiceId: false
  }
];
const PROVIDER_BY_ID = new Map(PROVIDERS.map((provider) => [provider.id, provider]));

const PROVIDER_PAGE_COPY = {
  elevenlabs: {
    generate: "Use saved library or shared voices and export reviewable MP3 or M4A files.",
    voices: "Browse premade and shared voices, then keep the ones you want in your registry.",
    clone: "Send a consented sample to ElevenLabs hosted cloning and save it for generation.",
    batch: "Process workbook rows with saved ElevenLabs voices and download the finished batch.",
    history: "Review completed ElevenLabs jobs, row results, and download bundles."
  },
  omnivoice: {
    generate: "Generate from synced presets or local clones. OmniVoice presets use strict supported voice attributes.",
    voices: "Sync curated presets, manage local clones, and keep saved voices ready for generation.",
    clone: "Store a consented sample locally for OmniVoice cloning and future reuse.",
    batch: "Process workbook rows with saved OmniVoice preset or clone ids and export the results.",
    history: "Review completed OmniVoice jobs, row results, and download bundles."
  }
};

const PAGES = [
  {
    id: "generate",
    path: "/generate",
    label: "Generate",
    title: "Generate audio",
    description: "Create one reviewable voice-note file.",
    icon: Wand2
  },
  {
    id: "voices",
    path: "/voices",
    label: "Voices",
    title: "Voice registry",
    description: "Sync presets, browse provider voices, and save voices.",
    icon: Volume2
  },
  {
    id: "clone",
    path: "/clone",
    label: "Clone",
    title: "Clone voice",
    description: "Upload or record a consented sample.",
    icon: Mic
  },
  {
    id: "batch",
    path: "/batch",
    label: "Batch",
    title: "Batch Excel",
    description: "Process an .xlsx workbook.",
    icon: FileSpreadsheet
  },
  {
    id: "history",
    path: "/history",
    label: "History",
    title: "Generation history",
    description: "Browse jobs, preview rows, and download audio.",
    icon: Download
  }
];

const PAGE_BY_ID = new Map(PAGES.map((page) => [page.id, page]));
const PAGE_BY_PATH = new Map(PAGES.map((page) => [page.path, page.id]));

function pageDescriptionFor(provider, pageId, fallback) {
  return PROVIDER_PAGE_COPY[provider]?.[pageId] || fallback;
}

function routeStateFromPath(pathname) {
  const storedProvider = window.localStorage.getItem("voice-message-provider") || "elevenlabs";
  const normalized = pathname === "/" ? "" : pathname.replace(/\/$/, "");
  const parts = normalized.split("/").filter(Boolean);
  const provider = PROVIDER_BY_ID.has(parts[0]) ? parts[0] : storedProvider;
  const routeParts = PROVIDER_BY_ID.has(parts[0]) ? parts.slice(1) : parts;
  const routePath = routeParts.length ? `/${routeParts.join("/")}` : "/generate";

  if (routePath === "/history" || routePath.startsWith("/history/")) {
    return {
      provider,
      page: "history",
      jobId: routePath.startsWith("/history/") ? decodeURIComponent(routePath.slice("/history/".length)) : null
    };
  }

  return {
    provider,
    page: PAGE_BY_PATH.get(routePath) || "generate",
    jobId: null
  };
}

function pagePath(provider, pageId, jobId = null) {
  const page = PAGE_BY_ID.get(pageId) || PAGE_BY_ID.get("generate");
  if (page.id === "history" && jobId) {
    return `/${provider}/history/${encodeURIComponent(jobId)}`;
  }
  return `/${provider}${page.path}`;
}

function apiPath(provider, suffix) {
  return `/api/${provider}${suffix}`;
}

function modelLabel(provider, modelId) {
  if (provider === "omnivoice") return "OmniVoice Batch";
  if (modelId === "eleven_v3") return "Eleven v3 Natural";
  if (modelId === "eleven_multilingual_v2") return "Multilingual v2";
  return modelId || "ElevenLabs";
}

function voiceSourceLabel(voice) {
  if (voice.source_type === "cloned") return "Local clone";
  if (voice.source_type === "voice_design") {
    return voice.provider_metadata?.mode === "auto" ? "Auto preset" : "Preset";
  }
  if (voice.source_type === "elevenlabs_library") return "Library";
  return "Saved";
}

function previewSupported(provider, voice) {
  if (provider === "elevenlabs") return true;
  return Boolean(voice.provider_metadata?.preview_url || voice.provider_metadata?.labels?.preview_url);
}

function voiceUseCase(voice) {
  const value =
    voice.provider_metadata?.voice_message_studio_profile?.use_case ||
    voice.provider_metadata?.labels?.use_case ||
    "general";
  return String(value).replaceAll("_", " ").replaceAll("-", " ");
}

function estimateSeconds(text, wpm) {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  if (!words) return 0;
  return Math.round((words / Math.max(Number(wpm) || 1, 1)) * 600) / 10;
}

function apiErrorMessage(detail, fallback) {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return fallback;

  const fields = detail
    .map((issue) => issue?.loc?.at(-1))
    .filter(Boolean)
    .map((field) =>
      String(field)
        .replaceAll("_", " ")
        .replace(/^./, (character) => character.toUpperCase())
    );
  const uniqueFields = [...new Set(fields)];
  if (uniqueFields.length === 0) return fallback;
  return `Check required field${uniqueFields.length === 1 ? "" : "s"}: ${uniqueFields.join(", ")}.`;
}

async function apiJson(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {})
    }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiErrorMessage(payload.detail, response.statusText || "Request failed"));
  }
  return payload;
}

function LoginScreen({ config, onLogin }) {
  const target = useRef(null);
  const [loginError, setLoginError] = useState("");

  useEffect(() => {
    if (config.auth_mode !== "google") return undefined;

    const initialize = () => {
      if (!window.google || !target.current) return;
      target.current.replaceChildren();
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          try {
            setLoginError("");
            const response = await apiJson("/api/auth/google", {
              method: "POST",
              body: JSON.stringify({ credential })
            });
            onLogin(response.user);
          } catch (error) {
            setLoginError(error.message || "Google login failed");
          }
        },
        auto_select: false,
        cancel_on_tap_outside: true
      });
      window.google.accounts.id.renderButton(target.current, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        width: 320
      });
    };

    const existing = document.querySelector("script[data-google-identity]");
    if (existing) {
      if (window.google) initialize();
      else existing.addEventListener("load", initialize, { once: true });
      return undefined;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = "true";
    script.addEventListener("load", initialize, { once: true });
    document.head.appendChild(script);
    return undefined;
  }, [config, onLogin]);

  async function developmentLogin() {
    try {
      setLoginError("");
      const response = await apiJson("/api/auth/development", { method: "POST" });
      onLogin(response.user);
    } catch (error) {
      setLoginError(error.message || "Login failed");
    }
  }

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function passwordLogin(event) {
    event.preventDefault();
    setSubmitting(true);
    try {
      setLoginError("");
      const response = await apiJson("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      onLogin(response.user);
    } catch (error) {
      setLoginError(error.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-brand-mark">
          <Volume2 size={24} />
        </div>
        <h1 id="login-title">Voice Message Studio</h1>
        <p>Sign in to create, clone, and manage reviewable voice-note audio.</p>
        {config.auth_mode === "google" ? (
          <div ref={target} className="google-button" />
        ) : (
          <button className="google-fallback" onClick={developmentLogin}>
            <span className="google-g">G</span>
            Continue locally
          </button>
        )}
        {config.password_enabled && (
          <>
            <div className="login-divider">
              <span>or</span>
            </div>
            <form className="credential-form" onSubmit={passwordLogin}>
              <input
                type="text"
                placeholder="Username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
              <input
                type="password"
                placeholder="Password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="submit"
                className="primary-button"
                disabled={!username || !password || submitting}
              >
                {submitting ? "Signing in..." : "Sign in"}
              </button>
            </form>
          </>
        )}
        {loginError && <p className="login-error">{loginError}</p>}
      </section>
    </main>
  );
}

function App() {
  const initialRoute = routeStateFromPath(window.location.pathname);
  const [config, setConfig] = useState(null);
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [bootError, setBootError] = useState("");
  const [health, setHealth] = useState(null);
  const [voices, setVoices] = useState([]);
  const [ttsForm, setTtsForm] = useState({
    text: "",
    voice_id: "",
    voice_name: "",
    accent: "us",
    speech_context: "outreach_conversational",
    target_seconds: 55,
    wpm: 135,
    export_m4a: true
  });
  const [cloneForm, setCloneForm] = useState({
    name: "",
    accent: "neutral",
    description: "",
    reference_text: "",
    consent_confirmed: false,
    sample: null
  });
  const [batchFile, setBatchFile] = useState(null);
  const [result, setResult] = useState(null);
  const [batchResult, setBatchResult] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobDetail, setJobDetail] = useState(null);
  const [omnivoiceContexts, setOmnivoiceContexts] = useState([]);
  const [historyJobId, setHistoryJobId] = useState(initialRoute.jobId);
  const [providerVoiceOptions, setProviderVoiceOptions] = useState([]);
  const [providerVoiceOptionsLoaded, setProviderVoiceOptionsLoaded] = useState(false);
  const [providerSort, setProviderSort] = useState("trending");
  const [providerAccent, setProviderAccent] = useState("us");
  const [providerPremadeOnly, setProviderPremadeOnly] = useState(true);
  const [providerPage, setProviderPage] = useState(0);
  const [providerMeta, setProviderMeta] = useState({ has_more: false, total_count: null, page: 0 });
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [activePage, setActivePage] = useState(initialRoute.page);
  const [activeProvider, setActiveProvider] = useState(initialRoute.provider);

  useEffect(() => {
    let active = true;
    Promise.all([apiJson("/api/config"), apiJson("/api/auth/me")])
      .then(([configPayload, sessionPayload]) => {
        if (!active) return;
        setConfig(configPayload);
        setUser(sessionPayload.user);
        setTtsForm((current) => ({
          ...current,
          target_seconds: configPayload.default_target_seconds,
          wpm: configPayload.default_wpm
        }));
      })
      .catch((error) => {
        if (active) setBootError(error.message || "Could not load Voice Message Studio");
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    refreshBootData(activeProvider).catch((error) => setError(error.message));
  }, [user, activeProvider]);

  useEffect(() => {
    const handlePopState = () => {
      const route = routeStateFromPath(window.location.pathname);
      setActiveProvider(route.provider);
      setActivePage(route.page);
      setHistoryJobId(route.jobId);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!user || activeProvider !== "elevenlabs" || activePage !== "voices" || providerVoiceOptionsLoaded) return;
    refreshProviderVoiceOptions().catch((error) => setError(error.message));
  }, [user, activeProvider, activePage, providerVoiceOptionsLoaded]);

  useEffect(() => {
    if (!user || activePage !== "history") return;
    if (historyJobId) {
      if (!jobDetail || jobDetail.job_id !== historyJobId) {
        apiJson(apiPath(activeProvider, `/jobs/${encodeURIComponent(historyJobId)}`))
          .then(setJobDetail)
          .catch((error) => setError(error.message));
      }
    } else {
      refreshJobs(activeProvider).catch((error) => setError(error.message));
    }
  }, [user, activeProvider, activePage, historyJobId]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [activePage]);

  useEffect(() => {
    window.localStorage.setItem("voice-message-provider", activeProvider);
    const target = pagePath(activeProvider, activePage, historyJobId);
    if (window.location.pathname !== target) {
      window.history.replaceState({}, "", target);
    }
  }, [activeProvider, activePage, historyJobId]);

  useEffect(() => {
    setProviderVoiceOptions([]);
    setProviderVoiceOptionsLoaded(false);
    setProviderMeta({ has_more: false, total_count: null, page: 0 });
    setProviderPage(0);
    setResult(null);
    setBatchResult(null);
    setJobDetail(null);
  }, [activeProvider]);

  async function refreshBootData(provider) {
    const [healthPayload, voicePayload, jobsPayload] = await Promise.all([
      apiJson(apiPath(provider, "/health")),
      apiJson(apiPath(provider, "/voices")),
      apiJson(apiPath(provider, "/jobs"))
    ]);
    setHealth(healthPayload);
    setVoices(voicePayload);
    setJobs(jobsPayload);
    refreshContexts(provider).catch(() => {});
  }

  async function logout() {
    await apiJson("/api/auth/logout", { method: "POST" });
    setUser(null);
    setHealth(null);
    setVoices([]);
    setJobs([]);
    setJobDetail(null);
    setResult(null);
    setBatchResult(null);
    setStatus("");
    setError("");
  }

  const estimatedSeconds = useMemo(
    () => estimateSeconds(ttsForm.text, ttsForm.wpm),
    [ttsForm.text, ttsForm.wpm]
  );
  const preWarning =
    estimatedSeconds > Number(ttsForm.target_seconds) && !result?.warning
      ? {
          level: "yellow",
          code: "estimated_target_exceeded",
          message: `Estimated ${estimatedSeconds}s is above the ${ttsForm.target_seconds}s target. Generation is allowed; shorten text or raise WPM if this is meant for LinkedIn.`
        }
      : null;

  async function refreshVoices() {
    const payload = await apiJson(apiPath(activeProvider, "/voices"));
    setVoices(payload);
    return payload;
  }

  async function refreshContexts(provider = activeProvider) {
    if (provider !== "omnivoice") {
      setOmnivoiceContexts([]);
      return [];
    }
    const payload = await apiJson(apiPath(provider, "/speech-contexts"));
    setOmnivoiceContexts(payload);
    return payload;
  }

  async function previewContext(design) {
    // Design-only preview; returns base64 wav. Throws on failure.
    return apiJson(apiPath(activeProvider, "/speech-contexts/preview"), {
      method: "POST",
      body: JSON.stringify(design)
    });
  }

  async function saveContext(contextReq) {
    setError("");
    setStatus("");
    setBusy("save-context");
    try {
      const saved = await apiJson(apiPath(activeProvider, "/speech-contexts"), {
        method: "POST",
        body: JSON.stringify(contextReq)
      });
      await refreshContexts();
      setStatus(`Saved speech context "${saved.name}".`);
      return saved;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setBusy("");
    }
  }

  async function deleteContext(contextId) {
    setError("");
    setStatus("");
    try {
      await apiJson(apiPath(activeProvider, `/speech-contexts/${encodeURIComponent(contextId)}`), {
        method: "DELETE"
      });
      await refreshContexts();
    } catch (err) {
      setError(err.message);
    }
  }

  async function refreshJobs(provider = activeProvider) {
    const payload = await apiJson(apiPath(provider, "/jobs"));
    setJobs(payload);
    return payload;
  }

  async function openJob(jobId) {
    setHistoryJobId(jobId);
    setActivePage("history");
    const target = pagePath(activeProvider, "history", jobId);
    if (window.location.pathname !== target) {
      window.history.pushState({}, "", target);
    }
    setJobDetail(null);
    setError("");
    setBusy("job-detail");
    try {
      const detail = await apiJson(apiPath(activeProvider, `/jobs/${encodeURIComponent(jobId)}`));
      setJobDetail(detail);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function closeJob() {
    setHistoryJobId(null);
    setJobDetail(null);
    const target = pagePath(activeProvider, "history");
    if (window.location.pathname !== target) {
      window.history.pushState({}, "", target);
    }
  }

  async function loadProviderVoices({
    page = providerPage,
    sort = providerSort,
    accent = providerAccent,
    premadeOnly = providerPremadeOnly,
    showStatus = false
  } = {}) {
    if (activeProvider !== "elevenlabs") {
      setProviderVoiceOptions([]);
      setProviderVoiceOptionsLoaded(true);
      setProviderMeta({ has_more: false, total_count: null, page: 0 });
      return { voices: [], page: 0, has_more: false, total_count: 0, sort, accent };
    }
    if (showStatus) {
      setError("");
      setStatus("");
    }
    setBusy("provider-voices");
    try {
      const params = new URLSearchParams({
        page: String(Math.max(page, 0)),
        page_size: "20",
        sort,
        accent,
        premade_only: premadeOnly ? "true" : "false"
      });
      const payload = await apiJson(apiPath(activeProvider, `/voices/options?${params.toString()}`));
      setProviderVoiceOptions(payload.voices);
      setProviderMeta({
        has_more: payload.has_more,
        total_count: payload.total_count,
        page: payload.page
      });
      setProviderPage(payload.page);
      setProviderSort(payload.sort);
      setProviderAccent(payload.accent);
      setProviderPremadeOnly(premadeOnly);
      setProviderVoiceOptionsLoaded(true);
      if (showStatus) {
        const accentLabel = ACCENT_LABELS[payload.accent] || payload.accent;
        const scope = premadeOnly ? "premade" : "library";
        setStatus(`Showing ${payload.voices.length} ${accentLabel} ${scope} voice(s) — page ${payload.page + 1}.`);
      }
      return payload;
    } finally {
      setBusy("");
    }
  }

  function refreshProviderVoiceOptions(showStatus = false) {
    return loadProviderVoices({ showStatus });
  }

  async function selectProviderVoice(option) {
    setError("");
    setStatus("");
    setBusy(`provider-voice-${option.id}`);
    try {
      let saved = voices.find(
        (voice) =>
          voice.voice_id === option.id ||
          (voice.provider_metadata && voice.provider_metadata.shared_voice_id === option.id)
      );
      if (!saved) {
        saved = await apiJson(apiPath(activeProvider, `/voice-options/${encodeURIComponent(option.id)}/save`), {
          method: "POST",
          body: JSON.stringify({
            public_owner_id: option.public_owner_id,
            name: option.display_name,
            accent: option.accent
          })
        });
        await refreshVoices();
      }
      setTtsForm((current) => ({
        ...current,
        voice_id: saved.voice_id,
        voice_name: saved.display_name,
        accent: saved.accent
      }));
      setProviderVoiceOptions((current) =>
        current.map((item) => (item.id === option.id ? { ...item, saved: true } : item))
      );
      setStatus(`${saved.display_name} is saved and available in Generate.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function addVoiceById(voiceId) {
    const trimmed = (voiceId || "").trim();
    if (!trimmed) {
      setError("Enter a voice id to add.");
      return;
    }
    setError("");
    setStatus("");
    setBusy("add-by-id");
    try {
      const saved = await apiJson(apiPath(activeProvider, "/voices/by-id"), {
        method: "POST",
        body: JSON.stringify({ voice_id: trimmed })
      });
      await refreshVoices();
      setTtsForm((current) => ({
        ...current,
        voice_id: saved.voice_id,
        voice_name: saved.display_name,
        accent: saved.accent
      }));
      setStatus(`${saved.display_name} added from voice id and ready in Generate.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function clearProviderCache() {
    setError("");
    setStatus("");
    try {
      const result = await apiJson(apiPath(activeProvider, "/voices/cache"), { method: "DELETE" });
      await loadProviderVoices({ page: 0 });
      setStatus(`Cleared ${result.cleared} cached entr${result.cleared === 1 ? "y" : "ies"} and refreshed.`);
    } catch (err) {
      setError(err.message);
    }
  }

  async function deleteVoice(voice) {
    setError("");
    setStatus("");
    setBusy(`delete-voice-${voice.id}`);
    try {
      const removed = await apiJson(apiPath(activeProvider, `/voices/${encodeURIComponent(voice.id)}`), {
        method: "DELETE"
      });
      await refreshVoices();
      if (providerVoiceOptionsLoaded) await refreshProviderVoiceOptions();
      setTtsForm((current) =>
        current.voice_id === removed.voice_id
          ? { ...current, voice_id: "", voice_name: "" }
          : current
      );
      setStatus(`Removed ${removed.display_name} from the registry.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function refreshHistory() {
    setError("");
    setStatus("");
    setBusy("jobs");
    try {
      const payload = await refreshJobs();
      setStatus(`Loaded ${payload.length} job(s).`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function navigate(pageId) {
    const page = PAGE_BY_ID.get(pageId) || PAGE_BY_ID.get("generate");
    setActivePage(page.id);
    if (page.id === "history") setHistoryJobId(null);
    const target = pagePath(activeProvider, page.id);
    if (window.location.pathname !== target) {
      window.history.pushState({}, "", target);
    }
  }

  function switchProvider(providerId) {
    if (!PROVIDER_BY_ID.has(providerId) || providerId === activeProvider) return;
    setActiveProvider(providerId);
    setActivePage("generate");
    setHistoryJobId(null);
    setStatus("");
    setError("");
  }

  async function syncVoices() {
    setError("");
    setStatus("");
    setBusy("sync");
    try {
      const payload = await apiJson(apiPath(activeProvider, "/voices/sync"), { method: "POST" });
      await refreshVoices();
      if (providerVoiceOptionsLoaded) await refreshProviderVoiceOptions();
      setStatus(
        activeProvider === "elevenlabs"
          ? `Synced ${payload.length} English conversational American/Indian voice(s).`
          : `Synced ${payload.length} OmniVoice preset voice(s).`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function generateAudio(event) {
    event.preventDefault();
    setError("");
    setStatus("");
    setBatchResult(null);
    setResult(null);
    setBusy("generate");
    try {
      const payload = await apiJson(apiPath(activeProvider, "/tts"), {
        method: "POST",
        body: JSON.stringify({
          ...ttsForm,
          target_seconds: Number(ttsForm.target_seconds),
          wpm: Number(ttsForm.wpm)
        })
      });
      setResult(payload);
      if (payload.status === "completed") {
        setStatus("Audio generated and saved to disk.");
        await refreshJobs(activeProvider);
      } else {
        setError(payload.error || "Generation failed.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function cloneVoice(event) {
    event.preventDefault();
    setError("");
    setStatus("");
    setBusy("clone");
    try {
      if (!cloneForm.sample) {
        throw new Error("Add an uploaded file or live recording sample first.");
      }
      const form = new FormData();
      form.append("name", cloneForm.name);
      form.append("accent", cloneForm.accent);
      form.append("description", cloneForm.description);
      if (activeProvider === "omnivoice" && cloneForm.reference_text) {
        form.append("reference_text", cloneForm.reference_text);
      }
      form.append("consent_confirmed", cloneForm.consent_confirmed ? "true" : "false");
      form.append("sample", cloneForm.sample, cloneForm.sample.name || "recording.webm");
      const saved = await apiJson(apiPath(activeProvider, "/voices/clone"), { method: "POST", body: form });
      await refreshVoices();
      await refreshJobs(activeProvider);
      setTtsForm((current) => ({
        ...current,
        voice_id: saved.voice_id,
        voice_name: saved.display_name,
        accent: saved.accent
      }));
      setCloneForm({
        name: "",
        accent: "neutral",
        description: "",
        consent_confirmed: false,
        sample: null
      });
      setStatus(`Cloned and persisted ${saved.display_name}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function uploadBatch(event) {
    event.preventDefault();
    setError("");
    setStatus("");
    setResult(null);
    setBatchResult(null);
    setBusy("batch");
    try {
      if (!batchFile) throw new Error("Choose an .xlsx workbook first.");
      const form = new FormData();
      form.append("file", batchFile, batchFile.name);
      // Async submit: returns 202 + a running job; then poll until terminal.
      const job = await apiJson(apiPath(activeProvider, "/tts/batch"), { method: "POST", body: form });
      setBatchResult(job);
      setStatus(`Batch submitted (${job.total_rows} rows). Generating...`);

      const TERMINAL = new Set(["completed", "partial", "failed", "interrupted"]);
      let detail = job;
      while (!TERMINAL.has(detail.status)) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        detail = await apiJson(apiPath(activeProvider, `/jobs/${encodeURIComponent(job.job_id)}`));
        setBatchResult(detail);
      }
      await refreshJobs(activeProvider);
      setStatus(
        `Batch ${detail.status}: ${detail.completed_rows}/${detail.total_rows} completed` +
          (detail.failed_rows ? `, ${detail.failed_rows} failed.` : ".")
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function selectVoice(value) {
    if (!value) {
      setTtsForm((current) => ({
        ...current,
        voice_id: "",
        voice_name: ""
      }));
      return;
    }

    const voice = voices.find((item) => item.voice_id === value);
    setTtsForm((current) => ({
      ...current,
      voice_id: value,
      voice_name: voice?.display_name || current.voice_name,
      accent: voice?.accent || current.accent
    }));
  }

  function changeTtsAccent(accent) {
    setTtsForm((current) => {
      const selectedVoice = voices.find((voice) => voice.voice_id === current.voice_id);
      const shouldClearVoice = selectedVoice && selectedVoice.accent !== accent;
      return {
        ...current,
        accent,
        ...(shouldClearVoice ? { voice_id: "", voice_name: "" } : {})
      };
    });
  }

  if (authLoading) {
    return (
      <div className="loading-screen" aria-label="Loading">
        <RefreshCcw className="spin" size={24} />
      </div>
    );
  }
  if (!config) {
    return (
      <div className="fatal-screen">
        <AlertCircle size={24} />
        <strong>Voice Message Studio could not start</strong>
        <span>{bootError}</span>
      </div>
    );
  }
  if (!user) return <LoginScreen config={config} onLogin={setUser} />;

  const currentPage = PAGE_BY_ID.get(activePage) || PAGE_BY_ID.get("generate");
  const activeProviderMeta = PROVIDER_BY_ID.get(activeProvider) || PROVIDER_BY_ID.get("elevenlabs");

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">
            <Volume2 size={20} />
          </div>
          <div>
            <h1>Voice Message Studio</h1>
            <p>{activeProviderMeta.subtitle}</p>
          </div>
        </div>

        <ProviderSwitch
          activeProvider={activeProvider}
          onSelect={switchProvider}
        />

        <PageNav activePage={activePage} onNavigate={navigate} />

        <section className="rail-card">
          <div className="health-row">
            <span className={health?.provider_configured ? "dot good" : "dot warn"} />
            <span>{health?.provider_configured ? `${activeProviderMeta.label} ready` : `${activeProviderMeta.label} not ready`}</span>
          </div>
          <div className="rail-metrics">
            <span>
              <strong>{voices.length}</strong>
              voices
            </span>
            <span>
              <strong>{jobs.length}</strong>
              jobs
            </span>
          </div>
        </section>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h2>{currentPage.title}</h2>
            <p>{pageDescriptionFor(activeProvider, currentPage.id, currentPage.description)}</p>
          </div>
          <div className="topbar-actions">
            <div className="limit-pill">
              <span>{modelLabel(activeProvider, config.model_id)}</span>
              {config.max_duration_seconds}s hard limit
            </div>
            <div className="account-chip">
              {user.picture ? (
                <img src={user.picture} alt="" referrerPolicy="no-referrer" />
              ) : (
                <span className="avatar">{user.name?.[0] || "U"}</span>
              )}
              <div className="account-copy">
                <strong>{user.name}</strong>
                <span>{user.email}</span>
              </div>
              <button className="icon-button" onClick={logout} title="Sign out" aria-label="Sign out">
                <LogOut size={17} />
              </button>
            </div>
          </div>
        </header>

        {(status || error) && (
          <div className={`toast ${error ? "error" : "success"}`}>
            {error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
            <span>{error || status}</span>
          </div>
        )}

        {activePage === "generate" && (
          <GeneratePage
            activeProvider={activeProvider}
            config={config}
            voices={voices}
            ttsForm={ttsForm}
            setTtsForm={setTtsForm}
            selectVoice={selectVoice}
            changeTtsAccent={changeTtsAccent}
            estimatedSeconds={estimatedSeconds}
            result={result}
            preWarning={preWarning}
            generateAudio={generateAudio}
            omnivoiceContexts={omnivoiceContexts}
            previewContext={previewContext}
            saveContext={saveContext}
            deleteContext={deleteContext}
            busy={busy}
          />
        )}

        {activePage === "voices" && (
          <VoicesPage
            activeProvider={activeProvider}
            health={health}
            voices={voices}
            ttsForm={ttsForm}
            selectVoice={selectVoice}
            deleteVoice={deleteVoice}
            syncVoices={syncVoices}
            providerVoiceOptions={providerVoiceOptions}
            providerVoiceOptionsLoaded={providerVoiceOptionsLoaded}
            providerSort={providerSort}
            providerAccent={providerAccent}
            providerPremadeOnly={providerPremadeOnly}
            providerPage={providerPage}
            providerMeta={providerMeta}
            onProviderSort={(sort) => loadProviderVoices({ sort, page: 0, showStatus: true })}
            onProviderAccent={(accent) => loadProviderVoices({ accent, page: 0, showStatus: true })}
            onProviderPremade={(premadeOnly) => loadProviderVoices({ premadeOnly, page: 0, showStatus: true })}
            onProviderPage={(page) => loadProviderVoices({ page, showStatus: true })}
            refreshProviderVoiceOptions={refreshProviderVoiceOptions}
            clearProviderCache={clearProviderCache}
            addVoiceById={addVoiceById}
            selectProviderVoice={selectProviderVoice}
            busy={busy}
          />
        )}

        {activePage === "clone" && (
          <ClonePage
            activeProvider={activeProvider}
            cloneForm={cloneForm}
            setCloneForm={setCloneForm}
            cloneVoice={cloneVoice}
            busy={busy}
            accents={config.accents}
          />
        )}

        {activePage === "batch" && (
          <BatchPage
            activeProvider={activeProvider}
            batchFile={batchFile}
            setBatchFile={setBatchFile}
            uploadBatch={uploadBatch}
            busy={busy}
            batchResult={batchResult}
          />
        )}

        {activePage === "history" && (
          <HistoryPage
            activeProvider={activeProvider}
            jobs={jobs}
            jobDetail={jobDetail}
            historyJobId={historyJobId}
            openJob={openJob}
            closeJob={closeJob}
            refreshHistory={refreshHistory}
            busy={busy}
          />
        )}
      </main>
    </div>
  );
}

function PageNav({ activePage, onNavigate }) {
  return (
    <nav className="page-nav" aria-label="Main sections">
      {PAGES.map((page) => {
        const Icon = page.icon;
        return (
          <button
            type="button"
            key={page.id}
            className={activePage === page.id ? "active" : ""}
            aria-current={activePage === page.id ? "page" : undefined}
            onClick={() => onNavigate(page.id)}
          >
            <Icon size={17} />
            <span>{page.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function ProviderSwitch({ activeProvider, onSelect }) {
  return (
    <section className="provider-switch" aria-label="Provider">
      {PROVIDERS.map((provider) => (
        <button
          type="button"
          key={provider.id}
          className={activeProvider === provider.id ? "active" : ""}
          onClick={() => onSelect(provider.id)}
        >
          <strong>{provider.label}</strong>
          <span>{provider.shortLabel}</span>
        </button>
      ))}
    </section>
  );
}

function GeneratePage({
  activeProvider,
  config,
  voices,
  ttsForm,
  setTtsForm,
  selectVoice,
  changeTtsAccent,
  estimatedSeconds,
  result,
  preWarning,
  generateAudio,
  omnivoiceContexts,
  previewContext,
  saveContext,
  deleteContext,
  busy
}) {
  const filteredVoices = useMemo(
    () => voices.filter((voice) => voice.accent === ttsForm.accent),
    [voices, ttsForm.accent]
  );
  const selectedVoiceVisible = filteredVoices.some((voice) => voice.voice_id === ttsForm.voice_id);
  const accentLabel = ACCENT_LABELS[ttsForm.accent] || "selected accent";
  const isElevenLabs = activeProvider === "elevenlabs";
  const contextOptions = isElevenLabs
    ? (config.contexts || []).map((c) => ({ id: c.id, label: c.label }))
    : (omnivoiceContexts || []).map((c) => ({ id: c.id, label: c.name }));

  // Keep speech_context valid for the active provider's context set.
  useEffect(() => {
    if (contextOptions.length === 0) return;
    if (!contextOptions.some((c) => c.id === ttsForm.speech_context)) {
      setTtsForm((current) => ({ ...current, speech_context: contextOptions[0].id }));
    }
  }, [activeProvider, omnivoiceContexts.length, config.contexts]);
  const voiceSelectLabel = isElevenLabs ? "Voice" : "Voice sample";
  const providerNote = isElevenLabs
    ? "Saved library or shared voices appear here. You can still paste a direct ElevenLabs voice id when needed."
    : "Pick a voice sample and a speech context. Edit the context's voice design (instruct + settings) below.";

  return (
    <section className="work-grid">
      <form className="panel primary-panel" onSubmit={generateAudio}>
        <div className="panel-heading">
          <div>
            <h2>Generate Audio</h2>
            <p>
              Yellow warns before generation. Red appears only after measured audio exceeds the hard
              limit.
            </p>
          </div>
          <Wand2 size={22} />
        </div>

        <div className="provider-note">
          <strong>{isElevenLabs ? "Hosted library + hosted cloning" : "Voice sample + speech context"}</strong>
          <p>{providerNote}</p>
        </div>

        <label>
          Message text
          <textarea
            value={ttsForm.text}
            onChange={(event) => setTtsForm((current) => ({ ...current, text: event.target.value }))}
            rows={8}
            placeholder="Hey Priya, quick one. I noticed your team is hiring across outbound roles..."
          />
        </label>

        <div className="field-grid">
          <label>
            {voiceSelectLabel}
            <select
              value={selectedVoiceVisible ? ttsForm.voice_id : ""}
              onChange={(event) => selectVoice(event.target.value)}
            >
              <option value="">Choose {accentLabel} voice</option>
              {filteredVoices.length === 0 && (
                <option value="" disabled>
                  No {accentLabel} voices saved
                </option>
              )}
              {filteredVoices.map((voice) => (
                <option key={voice.id} value={voice.voice_id}>
                  {voice.display_name}
                </option>
              ))}
            </select>
          </label>
          {isElevenLabs ? (
            <label>
              Provider voice ID
              <input
                value={ttsForm.voice_id}
                onChange={(event) =>
                  setTtsForm((current) => ({ ...current, voice_id: event.target.value }))
                }
                placeholder="Paste voice_id"
              />
            </label>
          ) : (
            <label>
              Selected voice ID
              <input
                value={ttsForm.voice_id}
                readOnly
                className="readonly-input"
                placeholder="Select a saved preset or clone"
              />
            </label>
          )}
          <label>
            Speech context
            <select
              value={ttsForm.speech_context}
              onChange={(event) =>
                setTtsForm((current) => ({ ...current, speech_context: event.target.value }))
              }
            >
              {contextOptions.length === 0 && <option value="">No contexts</option>}
              {contextOptions.map((context) => (
                <option key={context.id} value={context.id}>
                  {context.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="control-row">
          <SegmentedAccent
            accents={config.accents}
            value={ttsForm.accent}
            onChange={changeTtsAccent}
          />
          <label className="small-input">
            Target sec
            <input
              type="number"
              min="1"
              max={config.max_duration_seconds}
              value={ttsForm.target_seconds}
              onChange={(event) =>
                setTtsForm((current) => ({ ...current, target_seconds: event.target.value }))
              }
            />
          </label>
          <label className="small-input">
            WPM
            <input
              type="number"
              min="60"
              max="240"
              value={ttsForm.wpm}
              onChange={(event) => setTtsForm((current) => ({ ...current, wpm: event.target.value }))}
            />
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={ttsForm.export_m4a}
              onChange={(event) =>
                setTtsForm((current) => ({ ...current, export_m4a: event.target.checked }))
              }
            />
            Export M4A
          </label>
        </div>

        <WarningBanner warning={result?.warning || preWarning} />

        <div className="form-footer">
          <div className="estimate">
            <strong>{estimatedSeconds}s</strong>
            <span>estimated at {ttsForm.wpm} WPM</span>
          </div>
          <button className="primary-button" disabled={busy === "generate" || !ttsForm.text || !ttsForm.voice_id}>
            <Play size={17} />
            {busy === "generate" ? "Generating..." : activeProvider === "omnivoice" ? "Generate (voice + context)" : "Generate MP3"}
          </button>
        </div>
      </form>

      <ResultPanel activeProvider={activeProvider} result={result} />

      {!isElevenLabs && (
        <OmniVoiceContextEditor
          contexts={omnivoiceContexts}
          selectedId={ttsForm.speech_context}
          onSelect={(id) => setTtsForm((current) => ({ ...current, speech_context: id }))}
          previewContext={previewContext}
          saveContext={saveContext}
          deleteContext={deleteContext}
          previewText={ttsForm.text}
          busy={busy}
        />
      )}
    </section>
  );
}

function VoicesPage({
  activeProvider,
  health,
  voices,
  ttsForm,
  selectVoice,
  deleteVoice,
  syncVoices,
  providerVoiceOptions,
  providerVoiceOptionsLoaded,
  providerSort,
  providerAccent,
  providerPremadeOnly,
  providerPage,
  providerMeta,
  onProviderSort,
  onProviderAccent,
  onProviderPremade,
  onProviderPage,
  refreshProviderVoiceOptions,
  clearProviderCache,
  addVoiceById,
  selectProviderVoice,
  busy
}) {
  const usCount = voices.filter((voice) => voice.accent === "us").length;
  const indiaCount = voices.filter((voice) => voice.accent === "in").length;
  const neutralCount = voices.filter((voice) => voice.accent === "neutral").length;
  const presetCount = voices.filter((voice) => voice.source_type === "voice_design").length;
  const cloneCount = voices.filter((voice) => voice.source_type === "cloned").length;
  const autoCount = voices.filter(
    (voice) => voice.source_type === "voice_design" && voice.provider_metadata?.mode === "auto"
  ).length;
  const savedVoiceIds = useMemo(() => new Set(voices.map((voice) => voice.voice_id)), [voices]);
  // Shared-library voices get a new workspace id once saved; resolve the selected
  // TTS voice back to its original shared id so the "Selected" pill still matches.
  const selectedProviderId = useMemo(() => {
    const record = voices.find((voice) => voice.voice_id === ttsForm.voice_id);
    const sharedId = record && record.provider_metadata && record.provider_metadata.shared_voice_id;
    return sharedId || ttsForm.voice_id;
  }, [voices, ttsForm.voice_id]);

  return (
    <div className="voices-stack">
      <section className="page-grid voices-page">
        <VoiceRegistryPanel
          activeProvider={activeProvider}
          health={health}
          voices={voices}
          ttsForm={ttsForm}
          selectVoice={selectVoice}
          deleteVoice={deleteVoice}
          syncVoices={syncVoices}
          busy={busy}
        />
        <section className="panel stat-panel">
          <div className="panel-heading">
            <div>
              <h2>{activeProvider === "elevenlabs" ? "Voice Mix" : "Voice Sources"}</h2>
              <p>
                {activeProvider === "elevenlabs"
                  ? "English, conversational, supported accents."
                  : "Saved presets and clones available for OmniVoice generation."}
              </p>
            </div>
            <Volume2 size={21} />
          </div>
          <div className="stat-grid">
            <span>
              <strong>{voices.length}</strong>
              Total
            </span>
            {activeProvider === "elevenlabs" ? (
              <>
                <span>
                  <strong>{usCount}</strong>
                  American
                </span>
                <span>
                  <strong>{indiaCount}</strong>
                  Indian
                </span>
                <span>
                  <strong>{neutralCount}</strong>
                  Neutral
                </span>
              </>
            ) : (
              <>
                <span>
                  <strong>{presetCount}</strong>
                  Presets
                </span>
                <span>
                  <strong>{cloneCount}</strong>
                  Clones
                </span>
                <span>
                  <strong>{autoCount}</strong>
                  Auto voices
                </span>
              </>
            )}
          </div>
        </section>
      </section>

      {activeProvider === "elevenlabs" ? (
        <>
          <ProviderVoiceOptionsPanel
            options={providerVoiceOptions}
            loaded={providerVoiceOptionsLoaded}
            savedVoiceIds={savedVoiceIds}
            selectedVoiceId={selectedProviderId}
            sortMode={providerSort}
            accent={providerAccent}
            premadeOnly={providerPremadeOnly}
            page={providerPage}
            meta={providerMeta}
            onSort={onProviderSort}
            onAccent={onProviderAccent}
            onPremade={onProviderPremade}
            onPage={onProviderPage}
            refreshProviderVoiceOptions={refreshProviderVoiceOptions}
            clearProviderCache={clearProviderCache}
            selectProviderVoice={selectProviderVoice}
            busy={busy}
          />
          <AddVoiceByIdPanel addVoiceById={addVoiceById} busy={busy} />
        </>
      ) : (
        <OmniVoiceSamplesPanel voices={voices} />
      )}
    </div>
  );
}

function OmniVoiceSamplesPanel({ voices }) {
  const samples = voices.filter((voice) => voice.source_type === "cloned");
  return (
    <section className="panel provider-options-panel">
      <div className="panel-title-row">
        <div>
          <h2>OmniVoice Voice Samples</h2>
          <p>OmniVoice voices are uploaded sample sound files. Add one on the Clone page.</p>
        </div>
        <Mic size={21} />
      </div>
      <div className="provider-note">
        <strong>Voice = a sample; voice design = a speech context</strong>
        <p>To generate, pick a voice sample <em>and</em> a speech context. Manage the voice design (instruct + settings) for each context from the bottom of the Generate page.</p>
      </div>
      {samples.length === 0 ? (
        <div className="empty-state compact-empty">
          <Mic size={26} />
          <p>No voice samples yet. Upload one on the Clone page.</p>
        </div>
      ) : (
        <div className="provider-chip-list" aria-label="Saved samples">
          {samples.map((voice) => (
            <span key={voice.id}>{voice.display_name}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function contextToForm(ctx) {
  const s = (ctx && ctx.settings) || {};
  return {
    instruct: ctx?.instruct ?? "neutral, conversational",
    language: ctx?.language ?? "",
    speed: s.speed ?? 1.0,
    duration: s.duration ?? 0,
    num_step: s.num_step ?? 32,
    guidance_scale: s.guidance_scale ?? 2.0,
    denoise: s.denoise ?? true,
    preprocess_prompt: s.preprocess_prompt ?? true,
    postprocess_output: s.postprocess_output ?? true
  };
}

function OmniVoiceContextEditor({
  contexts,
  selectedId,
  onSelect,
  previewContext,
  saveContext,
  deleteContext,
  previewText,
  busy
}) {
  const selected = contexts.find((c) => c.id === selectedId) || null;
  const [form, setForm] = useState(() => contextToForm(selected));
  const [newName, setNewName] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setForm(contextToForm(selected));
    setPreviewUrl("");
    setLocalError("");
  }, [selectedId, contexts.length]);

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function settings() {
    return {
      speed: Number(form.speed),
      duration: Number(form.duration) > 0 ? Number(form.duration) : null,
      num_step: Number(form.num_step),
      guidance_scale: Number(form.guidance_scale),
      denoise: form.denoise,
      preprocess_prompt: form.preprocess_prompt,
      postprocess_output: form.postprocess_output
    };
  }

  async function handlePreview() {
    setLocalError("");
    setPreviewing(true);
    try {
      const payload = await previewContext({
        text: previewText || "Hey there, this is a quick preview of this voice design.",
        instruct: form.instruct,
        language: form.language || null,
        settings: settings()
      });
      setPreviewUrl(`data:audio/${payload.audio_format || "wav"};base64,${payload.audio_b64}`);
    } catch (err) {
      setLocalError(err.message);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleSaveChanges() {
    if (!selected) return;
    setLocalError("");
    try {
      await saveContext({
        id: selected.id,
        name: selected.name,
        instruct: form.instruct,
        language: form.language || null,
        settings: settings()
      });
    } catch {
      /* surfaced via app status */
    }
  }

  async function handleSaveNew() {
    setLocalError("");
    if (!newName.trim()) {
      setLocalError("Give the new context a name.");
      return;
    }
    try {
      const saved = await saveContext({
        name: newName.trim(),
        instruct: form.instruct,
        language: form.language || null,
        settings: settings()
      });
      setNewName("");
      if (saved?.id) onSelect(saved.id);
    } catch {
      /* surfaced via app status */
    }
  }

  return (
    <section className="panel tone-panel">
      <div className="panel-title-row">
        <div>
          <h2>Voice Design — Speech Context</h2>
          <p>The selected context's design is applied to the chosen voice sample. Edit, preview, and save.</p>
        </div>
        <Wand2 size={20} />
      </div>

      <div className="tone-context-row">
        <label className="tone-field">
          Speech context
          <select value={selectedId || ""} onChange={(event) => onSelect(event.target.value)}>
            {contexts.length === 0 && <option value="">No contexts</option>}
            {contexts.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
        {selected && contexts.length > 1 && (
          <button type="button" className="voice-icon-button" title="Delete this context" onClick={() => deleteContext(selected.id)}>
            <Trash2 size={15} />
          </button>
        )}
      </div>

      <label className="tone-field tone-wide">
        Instruct (voice design attributes)
        <input
          value={form.instruct}
          onChange={(event) => update("instruct", event.target.value)}
          placeholder="male, american accent, middle-aged, very high pitch"
        />
      </label>

      <div className="tone-grid">
        <label className="tone-field">
          Language
          <input value={form.language} onChange={(event) => update("language", event.target.value)} placeholder="Auto" />
        </label>
        <label className="tone-field">
          Speed ({Number(form.speed).toFixed(2)})
          <input type="range" min="0.5" max="1.5" step="0.05" value={form.speed} onChange={(event) => update("speed", event.target.value)} />
        </label>
        <label className="tone-field">
          Duration (s, 0 = use speed)
          <input type="number" min="0" step="1" value={form.duration} onChange={(event) => update("duration", event.target.value)} />
        </label>
        <label className="tone-field">
          Inference steps ({form.num_step})
          <input type="range" min="4" max="64" step="1" value={form.num_step} onChange={(event) => update("num_step", event.target.value)} />
        </label>
        <label className="tone-field">
          Guidance scale ({Number(form.guidance_scale).toFixed(1)})
          <input type="range" min="0" max="4" step="0.1" value={form.guidance_scale} onChange={(event) => update("guidance_scale", event.target.value)} />
        </label>
      </div>

      <div className="tone-toggles">
        <label><input type="checkbox" checked={form.denoise} onChange={(e) => update("denoise", e.target.checked)} /> Denoise</label>
        <label><input type="checkbox" checked={form.preprocess_prompt} onChange={(e) => update("preprocess_prompt", e.target.checked)} /> Preprocess prompt</label>
        <label><input type="checkbox" checked={form.postprocess_output} onChange={(e) => update("postprocess_output", e.target.checked)} /> Postprocess output</label>
      </div>

      <div className="tone-actions">
        <button type="button" className="secondary-button" onClick={handlePreview} disabled={previewing || !form.instruct.trim()}>
          <Play size={16} />
          {previewing ? "Generating..." : "Preview design"}
        </button>
        {previewUrl && <audio controls src={previewUrl} />}
      </div>

      {localError && <p className="login-error">{localError}</p>}

      <div className="tone-save-row">
        <button type="button" className="secondary-button" onClick={handleSaveChanges} disabled={busy === "save-context" || !selected}>
          <Save size={16} />
          Save changes
        </button>
        <input className="tone-name-input" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New context name" />
        <button type="button" className="primary-button" onClick={handleSaveNew} disabled={busy === "save-context" || !newName.trim()}>
          <Plus size={16} />
          Add new
        </button>
      </div>
    </section>
  );
}

function AddVoiceByIdPanel({ addVoiceById, busy }) {
  const [voiceId, setVoiceId] = useState("");
  const adding = busy === "add-by-id";

  async function handleSubmit(event) {
    event.preventDefault();
    await addVoiceById(voiceId);
    setVoiceId("");
  }

  return (
    <section className="panel add-by-id-panel">
      <div className="panel-title-row">
        <div>
          <h2>Add Voice by ID</h2>
          <p>Paste any ElevenLabs voice id to add it directly, without searching the library.</p>
        </div>
      </div>
      <form className="add-by-id-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={voiceId}
          onChange={(event) => setVoiceId(event.target.value)}
          placeholder="e.g. 3gsg3cxXyFLcGIfNbM6C"
          aria-label="ElevenLabs voice id"
        />
        <button className="primary-button" type="submit" disabled={adding || !voiceId.trim()}>
          <Plus size={16} />
          {adding ? "Adding..." : "Add Voice"}
        </button>
      </form>
    </section>
  );
}

function ProviderVoiceOptionsPanel({
  options,
  loaded,
  savedVoiceIds,
  selectedVoiceId,
  sortMode,
  accent,
  premadeOnly,
  page,
  meta,
  onSort,
  onAccent,
  onPremade,
  onPage,
  refreshProviderVoiceOptions,
  clearProviderCache,
  selectProviderVoice,
  busy
}) {
  const isLoading = busy === "provider-voices";
  const hasMore = Boolean(meta && meta.has_more);
  const totalCount = meta && typeof meta.total_count === "number" ? meta.total_count : null;
  // Hide voices already in the registry (selected); selecting more is allowed (multi-select).
  const visibleOptions = useMemo(
    () =>
      options.filter(
        (option) =>
          !option.saved && !savedVoiceIds.has(option.id) && option.id !== selectedVoiceId
      ),
    [options, savedVoiceIds, selectedVoiceId]
  );
  const pageStart = visibleOptions.length > 0 ? page * 20 + 1 : 0;
  const pageEnd = page * 20 + visibleOptions.length;

  return (
    <section className="panel provider-options-panel">
      <div className="panel-title-row">
        <div>
          <h2>ElevenLabs Voice Options</h2>
          <p>
            {premadeOnly
              ? "Premade default voices — usable on the free plan, 20 per page."
              : "Full ElevenLabs voice library (requires a paid plan to generate), 20 per page."}
          </p>
        </div>
        <div className="panel-title-actions">
          <label className="premade-toggle" title="Show only premade default voices (free plan)">
            <input
              type="checkbox"
              checked={premadeOnly}
              onChange={(event) => onPremade(event.target.checked)}
              disabled={isLoading}
            />
            <span>Premade only</span>
          </label>
          {!premadeOnly && (
            <button
              className="icon-button"
              onClick={clearProviderCache}
              title="Clear cached voices and refetch from ElevenLabs"
              disabled={isLoading}
            >
              <Trash2 size={16} />
            </button>
          )}
          <button
            className="icon-button"
            onClick={() => refreshProviderVoiceOptions(true)}
            title="Refresh ElevenLabs voice options"
            disabled={isLoading}
          >
            <RefreshCcw className={isLoading ? "spin" : ""} size={16} />
          </button>
        </div>
      </div>

      <div className="provider-toolbar" aria-label="ElevenLabs voice filters and sorting">
        <div className="provider-filter-chips" aria-label="Filters">
          <span>English</span>
          {PROVIDER_ACCENT_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.id}
              className={accent === option.id ? "chip active" : "chip"}
              onClick={() => onAccent(option.id)}
              disabled={isLoading}
            >
              {option.label}
            </button>
          ))}
          <span>{premadeOnly ? "Premade (free)" : "Conversational"}</span>
        </div>
        <div className="provider-sort-control" aria-label="Sort ElevenLabs voices">
          <ArrowDownWideNarrow size={16} />
          {PROVIDER_SORTS.map((sort) => (
            <button
              type="button"
              key={sort.id}
              className={sortMode === sort.id ? "active" : ""}
              onClick={() => onSort(sort.id)}
              disabled={isLoading}
            >
              {sort.label}
            </button>
          ))}
        </div>
      </div>

      {!loaded && !isLoading ? (
        <div className="empty-state compact-empty">
          <Volume2 size={26} />
          <p>Open ElevenLabs voice options to listen and select voices.</p>
          <button className="secondary-button" onClick={() => refreshProviderVoiceOptions(true)}>
            <RefreshCcw size={16} />
            Load Options
          </button>
        </div>
      ) : visibleOptions.length === 0 ? (
        <div className="empty-state compact-empty">
          <AlertCircle size={26} />
          <p>
            {isLoading
              ? "Loading ElevenLabs voices..."
              : options.length === 0
                ? premadeOnly
                  ? "No premade voices for this accent. Try American, or turn off “Premade only”."
                  : "No voices found for this filter."
                : "Every voice on this page is already selected. Try the next page."}
          </p>
        </div>
      ) : (
        <>
          <div className="provider-table-wrap">
            <table className="provider-table">
              <thead>
                <tr>
                  <th>Voice</th>
                  <th>Language</th>
                  <th>Accent</th>
                  <th>Listen</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleOptions.map((option) => {
                  const saving = busy === `provider-voice-${option.id}`;
                  const voiceDetails = [
                    option.descriptive || option.category || "ElevenLabs",
                    option.use_case_label || "Conversational",
                    option.gender,
                    option.age
                  ].filter(Boolean);
                  return (
                    <tr key={option.id}>
                      <td>
                        <strong>{option.display_name}</strong>
                        <span>{voiceDetails.join(" · ")}</span>
                        {option.description && <small>{option.description}</small>}
                      </td>
                      <td>{option.language_label || "English"}</td>
                      <td>{option.accent_label || ACCENT_LABELS[option.accent] || option.accent}</td>
                      <td>
                        {option.preview_url ? (
                          <audio controls preload="none" src={option.preview_url} />
                        ) : (
                          <span className="muted-cell">No preview</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="secondary-button"
                          onClick={() => selectProviderVoice(option)}
                          disabled={isLoading || saving}
                        >
                          {saving ? "Selecting..." : "Select"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="provider-pagination" aria-label="ElevenLabs voice pagination">
            <span className="provider-pagination-info">
              {`Showing ${pageStart}–${pageEnd}`}
              {totalCount !== null ? ` of ${totalCount}` : ""}
            </span>
            <div className="provider-pagination-controls">
              <button
                type="button"
                className="secondary-button"
                onClick={() => onPage(page - 1)}
                disabled={isLoading || page <= 0}
              >
                Previous
              </button>
              <span className="provider-pagination-page">Page {page + 1}</span>
              <button
                type="button"
                className="secondary-button"
                onClick={() => onPage(page + 1)}
                disabled={isLoading || !hasMore}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function VoiceRegistryPanel({
  activeProvider,
  health,
  voices,
  ttsForm,
  selectVoice,
  deleteVoice,
  syncVoices,
  busy
}) {
  const audioRef = useRef(null);
  const [playingId, setPlayingId] = useState(null);
  const [copiedId, setCopiedId] = useState(null);

  function togglePreview(voice) {
    const audio = audioRef.current;
    if (!audio) return;
    if (playingId === voice.id) {
      audio.pause();
      setPlayingId(null);
      return;
    }
    audio.src = apiPath(activeProvider, `/voices/${encodeURIComponent(voice.id)}/preview`);
    audio.play().then(() => setPlayingId(voice.id)).catch(() => setPlayingId(null));
  }

  async function copyVoiceId(voice) {
    try {
      await navigator.clipboard.writeText(voice.voice_id);
    } catch {
      const area = document.createElement("textarea");
      area.value = voice.voice_id;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopiedId(voice.id);
    setTimeout(() => setCopiedId((current) => (current === voice.id ? null : current)), 1500);
  }

  return (
    <section className="panel voice-registry-panel">
      <div className="panel-title-row">
        <h2>{activeProvider === "elevenlabs" ? "ElevenLabs Registry" : "OmniVoice Registry"}</h2>
        <button
          className="icon-button"
          onClick={syncVoices}
          title={activeProvider === "elevenlabs" ? "Sync ElevenLabs voices" : "Sync OmniVoice presets"}
          disabled={busy === "sync"}
        >
          <RefreshCcw className={busy === "sync" ? "spin" : ""} size={16} />
        </button>
      </div>
      <div className="health-row">
        <span className={health?.provider_configured ? "dot good" : "dot warn"} />
        <span>
          {health?.provider_configured
            ? `${PROVIDER_BY_ID.get(activeProvider)?.label || "Provider"} ready`
            : `${PROVIDER_BY_ID.get(activeProvider)?.label || "Provider"} missing setup`}
        </span>
      </div>
      <audio ref={audioRef} onEnded={() => setPlayingId(null)} hidden />
      <div className="voice-list">
        {voices.length === 0 ? (
          <p className="empty">
            {activeProvider === "elevenlabs"
              ? "No voices saved yet. Sync ElevenLabs or add a voice ID."
              : "No voices saved yet. Sync OmniVoice presets or create a clone."}
          </p>
        ) : (
          voices.map((voice) => {
            const canPreview = previewSupported(activeProvider, voice);
            const accentLabel = voice.provider_metadata?.labels?.accent || ACCENT_LABELS[voice.accent] || "Neutral";
            const languageLabel = voice.provider_metadata?.labels?.language || "English";

            return (
              <div
                key={voice.id}
                className={`voice-row ${ttsForm.voice_id === voice.voice_id ? "selected" : ""}`}
              >
                <button
                  type="button"
                  className="voice-row-main"
                  onClick={() => selectVoice(voice.voice_id)}
                >
                  <span>{voice.display_name}</span>
                  <small>
                    {languageLabel} · {accentLabel} · {voiceUseCase(voice)} · {voiceSourceLabel(voice)}
                    {voice.provider_metadata?.labels?.descriptive
                      ? ` · ${voice.provider_metadata.labels.descriptive}`
                      : ""}
                  </small>
                </button>
                <div className="voice-row-actions">
                  <button
                    type="button"
                    className="voice-icon-button"
                    title={
                      canPreview
                        ? playingId === voice.id
                          ? "Pause preview"
                          : "Play preview"
                        : "Preview unavailable for this voice"
                    }
                    aria-label={`Preview ${voice.display_name}`}
                    onClick={() => togglePreview(voice)}
                    disabled={!canPreview}
                  >
                    {playingId === voice.id ? <Pause size={15} /> : <Play size={15} />}
                  </button>
                  <button
                    type="button"
                    className="voice-icon-button"
                    title={copiedId === voice.id ? "Copied!" : "Copy voice ID"}
                    aria-label={`Copy voice ID for ${voice.display_name}`}
                    onClick={() => copyVoiceId(voice)}
                  >
                    {copiedId === voice.id ? <CheckCircle2 size={15} /> : <Copy size={15} />}
                  </button>
                  <button
                    type="button"
                    className="voice-icon-button voice-delete-button"
                    title={`Delete ${voice.display_name}`}
                    aria-label={`Delete ${voice.display_name}`}
                    onClick={() => deleteVoice(voice)}
                    disabled={busy === `delete-voice-${voice.id}`}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

function ClonePage({ activeProvider, cloneForm, setCloneForm, cloneVoice, busy, accents }) {
  return (
    <section className="single-page">
      <ClonePanel
        activeProvider={activeProvider}
        cloneForm={cloneForm}
        setCloneForm={setCloneForm}
        cloneVoice={cloneVoice}
        busy={busy}
        accents={accents}
      />
    </section>
  );
}

function BatchPage({ activeProvider, batchFile, setBatchFile, uploadBatch, busy, batchResult }) {
  return (
    <section className="single-page">
      <BatchPanel
        activeProvider={activeProvider}
        batchFile={batchFile}
        setBatchFile={setBatchFile}
        uploadBatch={uploadBatch}
        busy={busy}
        batchResult={batchResult}
      />
    </section>
  );
}

function HistoryPage({ activeProvider, jobs, jobDetail, historyJobId, openJob, closeJob, refreshHistory, busy }) {
  if (historyJobId) {
    return (
      <JobDetailView
        activeProvider={activeProvider}
        jobId={historyJobId}
        jobDetail={jobDetail}
        closeJob={closeJob}
        busy={busy}
      />
    );
  }
  return <JobListView jobs={jobs} openJob={openJob} refreshHistory={refreshHistory} busy={busy} />;
}

function JobListView({ jobs, openJob, refreshHistory, busy }) {
  return (
    <section className="panel files-panel">
      <div className="panel-title-row">
        <div>
          <h2>History</h2>
          <p>Every generation run, newest first.</p>
        </div>
        <button
          className="icon-button"
          onClick={refreshHistory}
          title="Refresh history"
          disabled={busy === "jobs"}
        >
          <RefreshCcw className={busy === "jobs" ? "spin" : ""} size={16} />
        </button>
      </div>
      {jobs.length === 0 ? (
        <div className="empty-state compact-empty">
          <Download size={26} />
          <p>No jobs yet. Generate audio or run a batch to see history here.</p>
        </div>
      ) : (
        <div className="job-list">
          {jobs.map((job) => (
            <button
              key={job.job_id}
              type="button"
              className="job-row"
              onClick={() => openJob(job.job_id)}
            >
              <div className="job-row-main">
                <strong>{job.job_id}</strong>
                <span>
                  {job.kind === "batch" ? "Batch" : "Single"} · {formatDate(job.created_at)} ·{" "}
                  {job.completed_rows}/{job.total_rows} ok
                  {job.failed_rows ? `, ${job.failed_rows} failed` : ""}
                </span>
              </div>
              <span className={`job-badge ${jobBadgeClass(job.status)}`}>{job.status || "completed"}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function JobDetailView({ activeProvider, jobId, jobDetail, closeJob, busy }) {
  const loading = busy === "job-detail";
  const ready = jobDetail && jobDetail.job_id === jobId;
  return (
    <section className="panel files-panel">
      <div className="panel-title-row">
        <div className="job-detail-head">
          <button className="secondary-button" onClick={closeJob}>
            ← Back
          </button>
          <div>
            <h2>{jobId}</h2>
            {ready && (
              <p>
                <span className={`job-badge ${jobBadgeClass(jobDetail.status)}`}>
                  {jobDetail.status}
                </span>{" "}
                {jobDetail.kind === "batch" ? "Batch" : "Single"} · {formatDate(jobDetail.created_at)} ·{" "}
                {jobDetail.completed_rows}/{jobDetail.total_rows} ok
                {jobDetail.failed_rows ? `, ${jobDetail.failed_rows} failed` : ""}
                {jobDetail.error ? ` — ${jobDetail.error}` : ""}
              </p>
            )}
          </div>
        </div>
        {ready && jobDetail.status !== "running" && (
          <a
            className="primary-button"
            href={apiPath(activeProvider, `/jobs/${encodeURIComponent(jobId)}/download`)}
            download
          >
            <Download size={16} />
            Download ZIP
          </a>
        )}
      </div>
      {!ready ? (
        <div className="empty-state compact-empty">
          <p>{loading ? "Loading job..." : "Job not found."}</p>
        </div>
      ) : (
        <div className="job-rows">
          {jobDetail.rows.map((row) => (
            <div
              key={row.index}
              className={row.status === "failed" ? "job-detail-row failed" : "job-detail-row"}
            >
              <div className="job-detail-row-head">
                <strong>
                  Row {row.index}
                  {row.voice_name ? ` · ${row.voice_name}` : ""}
                </strong>
                <span className={row.status === "completed" ? "job-badge ok" : "job-badge warn"}>
                  {row.status}
                </span>
              </div>
              <p className="job-detail-text">{row.text}</p>
              {row.mp3_url ? (
                <audio controls preload="none" src={row.mp3_url} />
              ) : (
                <span className="muted-cell">{row.error || "No audio produced"}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function SegmentedAccent({ accents, value, onChange }) {
  return (
    <div className="segmented" role="group" aria-label="Accent">
      {accents.map((accent) => (
        <button
          type="button"
          key={accent.id}
          className={value === accent.id ? "active" : ""}
          onClick={() => onChange(accent.id)}
        >
          {accent.label}
        </button>
      ))}
    </div>
  );
}

function WarningBanner({ warning }) {
  if (!warning) return null;
  return (
    <div className={`warning ${warning.level}`}>
      <AlertCircle size={18} />
      <div>
        <strong>{warning.level === "red" ? "Hard limit crossed" : "Pre-generation warning"}</strong>
        <p>{warning.message}</p>
      </div>
    </div>
  );
}

function ResultPanel({ activeProvider, result }) {
  return (
    <section className="panel result-panel">
      <div className="panel-heading">
        <div>
          <h2>Result</h2>
          <p>Saved files stay under the Docker-mounted data directory.</p>
        </div>
        <Download size={21} />
      </div>

      {!result ? (
        <div className="empty-state">
          <Volume2 size={28} />
          <p>Generated audio, measured duration, and downloads will appear here.</p>
        </div>
      ) : result.status === "failed" ? (
        <div className="failure-box">
          <AlertCircle size={20} />
          <div>
            <strong>Generation failed</strong>
            <p>{result.error}</p>
          </div>
        </div>
      ) : (
        <div className="result-stack">
          <div className="duration-strip">
            <span>
              Estimated <strong>{result.estimated_seconds}s</strong>
            </span>
            <span>
              Actual <strong>{result.actual_seconds}s</strong>
            </span>
            <span>
              Max <strong>{result.max_seconds}s</strong>
            </span>
          </div>
          {result.model_id && <div className="model-note">Generated with {modelLabel(activeProvider, result.model_id)}</div>}
          {result.mp3_url && <audio controls src={result.mp3_url} />}
          <div className="download-row">
            {result.mp3_url && (
              <a href={result.mp3_url} download>
                <Download size={16} />
                MP3
              </a>
            )}
            {result.m4a_url && (
              <a href={result.m4a_url} download>
                <Download size={16} />
                M4A
              </a>
            )}
            {result.transcript_url && (
              <a href={result.transcript_url} download>
                <Download size={16} />
                Text
              </a>
            )}
          </div>
          {result.m4a_url && (
            <code className="command">
              ffmpeg -i input.mp3 -ac 1 -c:a aac -b:a 64k -t 60 output.m4a
            </code>
          )}
        </div>
      )}
    </section>
  );
}

function ClonePanel({ activeProvider, cloneForm, setCloneForm, cloneVoice, busy, accents }) {
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const [recording, setRecording] = useState(false);

  async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      const file = new File([blob], "live-recording.webm", { type: blob.type });
      setCloneForm((current) => ({ ...current, sample: file }));
      stream.getTracks().forEach((track) => track.stop());
    };
    recorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

  function stopRecording() {
    recorderRef.current?.stop();
    setRecording(false);
  }

  return (
    <form className="panel compact-panel" onSubmit={cloneVoice}>
      <div className="panel-heading">
        <div>
          <h2>Clone Voice</h2>
          <p>
            {activeProvider === "elevenlabs"
              ? "Upload audio or record live. Consent is required."
              : "Save a local source sample for OmniVoice cloning. Consent is required."}
          </p>
        </div>
        <Mic size={21} />
      </div>
      <div className="field-grid two">
        <label>
          Voice name
          <input
            value={cloneForm.name}
            onChange={(event) => setCloneForm((current) => ({ ...current, name: event.target.value }))}
            placeholder="Amar clone"
          />
        </label>
        <label>
          Accent
          <select
            value={cloneForm.accent}
            onChange={(event) => setCloneForm((current) => ({ ...current, accent: event.target.value }))}
          >
            {accents.map((accent) => (
              <option key={accent.id} value={accent.id}>
                {accent.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Description
        <input
          value={cloneForm.description}
          onChange={(event) =>
            setCloneForm((current) => ({ ...current, description: event.target.value }))
          }
          placeholder="Consented founder voice sample"
        />
      </label>
      {activeProvider === "omnivoice" && (
        <label>
          Reference transcript (optional)
          <input
            value={cloneForm.reference_text}
            onChange={(event) =>
              setCloneForm((current) => ({ ...current, reference_text: event.target.value }))
            }
            placeholder="Exact words spoken in the sample (improves cloning)"
          />
        </label>
      )}
      <div className="sample-row">
        <label className="file-button">
          <Upload size={16} />
          Upload Sample
          <input
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.webm"
            onChange={(event) =>
              setCloneForm((current) => ({ ...current, sample: event.target.files?.[0] || null }))
            }
          />
        </label>
        <button type="button" className="secondary-button" onClick={recording ? stopRecording : startRecording}>
          {recording ? <Pause size={16} /> : <Mic size={16} />}
          {recording ? "Stop" : "Record"}
        </button>
        <span className="sample-name">{cloneForm.sample?.name || "No sample selected"}</span>
      </div>
      <label className="checkbox-line">
        <input
          type="checkbox"
          checked={cloneForm.consent_confirmed}
          onChange={(event) =>
            setCloneForm((current) => ({ ...current, consent_confirmed: event.target.checked }))
          }
        />
        I have permission to clone this voice.
      </label>
      <button className="primary-button clone-submit-button" disabled={busy === "clone" || !cloneForm.name}>
        <Plus size={17} />
        {busy === "clone" ? "Cloning..." : activeProvider === "omnivoice" ? "Save Clone" : "Clone and Save"}
      </button>
    </form>
  );
}

function BatchPanel({ activeProvider, batchFile, setBatchFile, uploadBatch, busy, batchResult }) {
  return (
    <form className="panel compact-panel" onSubmit={uploadBatch}>
      <div className="panel-heading">
        <div>
          <h2>Batch Excel</h2>
          <p>
            Use sheet <code>tts_requests</code>.{" "}
            {activeProvider === "elevenlabs"
              ? "Rows should reference saved ElevenLabs voices."
              : "Rows should reference saved OmniVoice preset or clone ids."}
          </p>
        </div>
        <FileSpreadsheet size={21} />
      </div>
      <label className="file-drop">
        <Upload size={18} />
        <span>{batchFile?.name || "Choose .xlsx workbook"}</span>
        <input
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(event) => setBatchFile(event.target.files?.[0] || null)}
        />
      </label>
      <button className="primary-button" disabled={busy === "batch" || !batchFile}>
        <Play size={17} />
        {busy === "batch" ? "Processing..." : "Process Workbook"}
      </button>
      {batchResult && (
        <div className="batch-summary">
          <div className="batch-summary-head">
            <span className={`job-badge ${jobBadgeClass(batchResult.status)}`}>
              {batchResult.status || "running"}
            </span>
            <strong>
              {(batchResult.completed_rows || 0) + (batchResult.failed_rows || 0)}/
              {batchResult.total_rows} rows
            </strong>
            {batchResult.failed_rows ? <span>{batchResult.failed_rows} failed</span> : null}
          </div>
          {batchResult.total_rows > 0 && (
            <div className="batch-progress">
              <div
                className="batch-progress-fill"
                style={{
                  width: `${Math.round(
                    (((batchResult.completed_rows || 0) + (batchResult.failed_rows || 0)) /
                      batchResult.total_rows) *
                      100
                  )}%`
                }}
              />
            </div>
          )}
          {batchResult.error && <small className="batch-error">{batchResult.error}</small>}
          <div className="batch-summary-actions">
            {batchResult.workbook_url && (
              <a href={batchResult.workbook_url} download>
                <Download size={16} />
                Results workbook
              </a>
            )}
            {batchResult.job_id && batchResult.status && batchResult.status !== "running" && (
              <a href={apiPath(activeProvider, `/jobs/${encodeURIComponent(batchResult.job_id)}/download`)} download>
                <Download size={16} />
                Download ZIP
              </a>
            )}
          </div>
        </div>
      )}
    </form>
  );
}

function jobBadgeClass(status) {
  if (status === "completed") return "ok";
  if (status === "running") return "info";
  return "warn";
}

createRoot(document.getElementById("root")).render(<App />);
