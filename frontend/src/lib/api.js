// Backend API client. All calls hit the FastAPI dev server on :7860 by default.

import { toast } from "./toast";

export const API_BASE =
  import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:7860";

export const WS_BASE = API_BASE.replace(/^http/, "ws");

const TOKEN_KEY = "rechord:auth:token";

// Read the latest token at call time (NOT at module load) so a sign-in
// during the session is picked up by the next request without a reload.
function _authHeaders() {
  try {
    const t = localStorage.getItem(TOKEN_KEY);
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
}

async function jfetch(path, init) {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ..._authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText} ${body}`);
  }
  return r.json();
}

// ── Consents API (Phase B) ──────────────────────────────────────

/** Record (or update) a single user consent. Requires authentication. */
export function grantConsent({ consent_type, version, granted = true }) {
  return jfetch("/consents", {
    method: "POST",
    body: JSON.stringify({ consent_type, version, granted }),
  });
}

/** Return every consent row for the current user. */
export function listMyConsents() {
  return jfetch("/consents/me");
}

/** Revoke all active grants of a consent_type. Returns `{revoked: <count>}`. */
export function revokeConsent(consent_type) {
  return jfetch(`/consents/${consent_type}`, { method: "DELETE" });
}

// ── Legal docs (markdown source from docs/legal/) ───────────────

/** Fetch one legal doc by slug ('terms' | 'privacy' | 'copyright' | 'consent'). */
export function getLegalDoc(docId) {
  return jfetch(`/legal/${docId}`);
}

/** Index of available legal docs. */
export function listLegalDocs() {
  return jfetch(`/legal`);
}

export function getFormats() {
  return jfetch("/formats");
}

export function getInstallHints() {
  return jfetch("/ops/install_hints");
}

export function submitFeedback(body) {
  return jfetch("/feedback", { method: "POST", body: JSON.stringify(body) });
}

export function getFeedbackSummary() {
  return jfetch("/feedback/summary");
}

export function getJob(id) {
  return jfetch(`/jobs/${id}`);
}

export function createJob(input, options) {
  return jfetch("/jobs", {
    method: "POST",
    body: JSON.stringify({ input, options }),
  });
}

/** Build a mixdown from a chosen subset of stems on an existing Stems-mode job. */
export function createMixdown(jobId, includedStems, targetSr = 48000) {
  return jfetch(`/jobs/${jobId}/mixdown`, {
    method: "POST",
    body: JSON.stringify({ included_stems: includedStems, target_sr: targetSr }),
  });
}

/** Build an A-B loop wav: trim [start_sec, end_sec] and repeat N times. */
export function createLoop(jobId, opts) {
  return jfetch(`/jobs/${jobId}/loop`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "instrumental_final",
      start_sec: opts.startSec,
      end_sec: opts.endSec,
      repeats: opts.repeats ?? 4,
      with_countin: opts.withCountin ?? true,
      target_sr: opts.targetSr ?? 48000,
    }),
  });
}

/** Beat grid + section markers (if D9 was run). */
export function getSections(jobId) {
  return jfetch(`/jobs/${jobId}/sections`);
}

/** Per-bar chord progression (if karaoke/pro analyze ran). */
export function getChords(jobId) {
  return jfetch(`/jobs/${jobId}/chords`);
}

/** Per-word lyrics with confidence (if faster-whisper ran). */
export function getLyrics(jobId) {
  return jfetch(`/jobs/${jobId}/lyrics`);
}

/** Save user-edited lyrics + optionally rebuild the vocals score.
 *  ``translations`` is a {verseNumber: text} map for bilingual side-by-side
 *  display (e.g. English worship lyrics paired with a Korean rendering). */
export function saveLyrics(jobId, words, rebuildScore = true, translations = null) {
  return jfetch(`/jobs/${jobId}/lyrics`, {
    method: "PUT",
    body: JSON.stringify({
      words,
      rebuild_score: rebuildScore,
      ...(translations ? { translations } : {}),
    }),
  });
}

/** AUX/second-keyboard patch cues per measure range. */
export function getAuxCues(jobId) {
  return jfetch(`/jobs/${jobId}/aux_cues`);
}

export function saveAuxCues(jobId, cues, rebuildScore = true) {
  return jfetch(`/jobs/${jobId}/aux_cues`, {
    method: "PUT",
    body: JSON.stringify({ cues, rebuild_score: rebuildScore }),
  });
}

/** Run the CLAP-based AUX patch suggester for this job. */
export function autoAuxCues(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/aux_cues/auto`, {
    method: "POST",
    body: JSON.stringify({
      measures_per_window: opts.measuresPerWindow ?? 1,
      top_k: opts.topK ?? 16,
      save: opts.save ?? true,
    }),
  });
}

/** Per-job rehearsal notes / arrangement annotations. */
export function listNotes(jobId) {
  return jfetch(`/jobs/${jobId}/notes`);
}
export function createNote(jobId, body) {
  return jfetch(`/jobs/${jobId}/notes`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
export function patchNote(jobId, noteId, body) {
  return jfetch(`/jobs/${jobId}/notes/${noteId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}
export function deleteNote(jobId, noteId) {
  return jfetch(`/jobs/${jobId}/notes/${noteId}`, { method: "DELETE" });
}

/** Setlist (server-side, multi-device-ready) endpoints. */
export function listSetlists() {
  return jfetch(`/setlists`);
}
export function createSetlistServer(name, jobIds = []) {
  return jfetch(`/setlists`, {
    method: "POST",
    body: JSON.stringify({ name, job_ids: jobIds }),
  });
}
export function patchSetlist(setlistId, patch) {
  return jfetch(`/setlists/${setlistId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
export function deleteSetlistServer(setlistId) {
  return jfetch(`/setlists/${setlistId}`, { method: "DELETE" });
}
export function addJobToSetlist(setlistId, jobId) {
  return jfetch(`/setlists/${setlistId}/jobs/${jobId}`, { method: "POST" });
}
export function removeJobFromSetlist(setlistId, jobId) {
  return jfetch(`/setlists/${setlistId}/jobs/${jobId}`, { method: "DELETE" });
}

/** Render binaural / HRTF-widened version of an artifact for headphones. */
export function createBinaural(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/binaural`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "instrumental_final",
      width: opts.width ?? 1.0,
    }),
  });
}

/** LUFS-target loudness normalisation + optional 3-band EQ. */
export function masterArtifact(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/master`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "instrumental_final",
      target_platform: opts.targetPlatform ?? "spotify",
      custom_lufs: opts.customLufs ?? -14,
      low_db: opts.lowDb ?? 0,
      mid_db: opts.midDb ?? 0,
      high_db: opts.highDb ?? 0,
    }),
  });
}

/** Gentle vocal pitch correction (CREPE + WORLD). */
export function autotuneArtifact(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/autotune`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "vocals_final",
      key_root: opts.keyRoot ?? "C",
      scale: opts.scale ?? "major",
      correction_strength: opts.strength ?? 0.65,
      snap_window_cents: opts.snapCents ?? 50,
    }),
  });
}

/** Cancel a queued or running job. */
export function cancelJob(jobId) {
  return jfetch(`/jobs/${jobId}`, { method: "DELETE" });
}

/** Grade a recorded performance against the job's vocal reference. */
export function gradePerformance(jobId, blob, reference = "vocals_final") {
  const fd = new FormData();
  fd.append("recording", blob, "user_recording.webm");
  fd.append("reference", reference);
  return fetch(`${API_BASE}/jobs/${jobId}/grade`, {
    method: "POST",
    body: fd,
  }).then((r) => {
    if (!r.ok) {
      return r.text().then((t) => { throw new Error(`${r.status} ${t}`); });
    }
    return r.json();
  });
}

/** Render a 5.1 surround mix from the job's stems. */
export function createSurround(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/surround`, {
    method: "POST",
    body: JSON.stringify({ sample_rate: opts.sampleRate ?? 48000 }),
  });
}

/** Encode a job artifact to DSD (.dsf) for audiophile playback. */
export function createDsd(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/dsd`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "instrumental_final",
      rate: opts.rate ?? "dsd64",
    }),
  });
}

/** Worship-mode helpers. */
export function createPedalTone(jobId, opts = {}) {
  return jfetch(`/jobs/${jobId}/pedal_tone`, {
    method: "POST",
    body: JSON.stringify({
      key_root: opts.keyRoot,
      mode: opts.mode ?? "major",
      duration_sec: opts.durationSec ?? 16,
    }),
  });
}
export function createSegue(jobId, opts) {
  return jfetch(`/jobs/${jobId}/segue`, {
    method: "POST",
    body: JSON.stringify({
      next_job_id: opts.nextJobId,
      bridge_key: opts.bridgeKey ?? null,
      bridge_seconds: opts.bridgeSeconds ?? 8,
      crossfade_seconds: opts.crossfadeSeconds ?? 2,
      source: opts.source ?? "instrumental_final",
    }),
  });
}

/** Pitch-preserving slowdown of one artifact (Tempo-style practice mode). */
export function createSlowdown(jobId, opts) {
  return jfetch(`/jobs/${jobId}/slowdown`, {
    method: "POST",
    body: JSON.stringify({
      source: opts.source ?? "instrumental_final",
      tempo_ratio: opts.tempoRatio,
      stem_kind: opts.stemKind ?? "instrumental",
    }),
  });
}

/** Direct URL for an artifact (for <audio>/wavesurfer to fetch). */
export function artifactUrl(jobId, artifactKey) {
  return `${API_BASE}/jobs/${jobId}/download/${artifactKey}`;
}

/** Upload a file with progress callback. Returns the upload info JSON. */
export function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/uploads`);
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch (e) { reject(e); }
      } else {
        reject(new Error(`upload failed: ${xhr.status} ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(fd);
  });
}

/**
 * Open a job progress WebSocket with automatic reconnection.
 *
 * If the socket drops *before* the job reaches a terminal state (done /
 * error / cancelled), we transparently reconnect with exponential
 * backoff (0.5s → 1s → 2s → 4s, capped at 8s, up to 6 attempts). The
 * backend replays missed events from its 200-event history buffer on
 * reconnect, so the progress bar resumes instead of freezing on a flaky
 * network. Returns a controller with ``.close()`` to stop for good.
 */
export function openProgressSocket(jobId, onEvent, onClose, onStatus) {
  let ws = null;
  let closedByCaller = false;
  let terminal = false;
  let attempt = 0;
  const MAX_ATTEMPTS = 6;

  const emitStatus = (state, detail) => {
    if (onStatus) {
      try { onStatus(state, detail); } catch { /* listener bug — never crash the socket */ }
    }
  };

  const isTerminalEvent = (data) => {
    const stage = (data?.stage || "").toLowerCase();
    const type = (data?.type || "").toLowerCase();
    return type === "done" || stage === "done"
      || stage === "error" || stage === "cancelled"
      || (data?.message || "").includes("FAILED");
  };

  const connect = () => {
    emitStatus(attempt === 0 ? "connecting" : "reconnecting", { attempt, maxAttempts: MAX_ATTEMPTS });
    ws = new WebSocket(`${WS_BASE}/jobs/${jobId}/progress`);
    ws.onopen = () => {
      attempt = 0;
      emitStatus("open");
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (isTerminalEvent(data)) terminal = true;
        onEvent(data);
      } catch { /* ignore */ }
    };
    ws.onclose = (ev) => {
      if (closedByCaller || terminal) {
        emitStatus("closed", { reason: terminal ? "terminal" : "caller" });
        if (onClose) onClose(ev);
        return;
      }
      // Unexpected drop mid-job → reconnect with backoff.
      if (attempt < MAX_ATTEMPTS) {
        const delay = Math.min(8000, 500 * 2 ** attempt);
        attempt += 1;
        emitStatus("reconnecting", { attempt, maxAttempts: MAX_ATTEMPTS, delayMs: delay });
        setTimeout(() => { if (!closedByCaller && !terminal) connect(); }, delay);
      } else {
        emitStatus("failed", { attempts: attempt });
        if (onClose) onClose(ev);
      }
    };
  };

  connect();

  // Return a controller object that's also usable like the old raw ws
  // for ``.close()`` callers.
  return {
    close: () => {
      closedByCaller = true;
      try { ws && ws.close(); } catch { /* ignore */ }
    },
    get readyState() { return ws ? ws.readyState : WebSocket.CLOSED; },
  };
}

/** Chat — list all conversations belonging to the current user. */
export function listChatSessions() {
  return jfetch(`/chat/sessions`);
}

/** Chat — create or reuse a session keyed by the browser-stored UUID. */
export function createChatSession(sessionId) {
  return jfetch(`/chat/sessions`, {
    method: "POST",
    body: JSON.stringify(sessionId ? { session_id: sessionId } : {}),
  });
}

/** Chat — fetch persisted history for a session. */
export function getChatSession(sessionId) {
  return jfetch(`/chat/sessions/${sessionId}`);
}

/** Chat — rename a conversation (or other metadata). */
export function patchChatSession(sessionId, patch) {
  return jfetch(`/chat/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** Chat — non-streaming turn. Kept as a fallback. */
export function postChatMessage(sessionId, body) {
  return jfetch(`/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Chat — SSE-streamed turn (M2).
 *  Calls ``onEvent`` for every parsed frame. Frame shape:
 *    { type: "delta",      text }                — partial token
 *    { type: "confidence", value }              — parsed <confidence>
 *    { type: "message",    message }            — final persisted msg
 *    { type: "error",      detail, status? }    — stream-side failure
 *    { type: "done" }                           — terminator
 *
 *  Throws on non-2xx responses (e.g. 429 rate limit) before the stream
 *  starts. The thrown Error carries ``status`` and ``retryAfter`` (seconds)
 *  for rate-limit handling.
 */
export async function streamChatMessage(sessionId, body, onEvent, signal) {
  const r = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    let detail = null;
    try { detail = await r.json(); } catch { /* not JSON */ }
    const err = new Error(`${r.status} ${r.statusText}`);
    err.status = r.status;
    err.detail = detail;
    const ra = r.headers.get("Retry-After");
    err.retryAfter =
      detail?.detail?.retry_after ?? (ra ? parseFloat(ra) : null);
    throw err;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const lines = frame.split("\n").filter((l) => l.startsWith("data:"));
      if (!lines.length) continue;
      const data = lines.map((l) => l.slice(5).trim()).join("\n");
      if (!data) continue;
      try {
        const ev = JSON.parse(data);
        onEvent(ev);
      } catch {
        /* malformed frame — ignore */
      }
    }
  }
}

/** Chat — drop a session (and any in-memory state) on the server. */
export function deleteChatSession(sessionId) {
  return jfetch(`/chat/sessions/${sessionId}`, { method: "DELETE" });
}

/** Chat — attach an audio file. Triggers a lightweight key/BPM analysis
 *  on the backend. Returns the attachment record; pass its ``id`` in the
 *  next ``streamChatMessage`` call's ``attachment_ids``. */
export function attachChatFile(sessionId, file) {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(
    `${API_BASE}/chat/sessions/${sessionId}/attach/upload`,
    { method: "POST", body: fd },
  ).then(async (r) => {
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      throw new Error(`${r.status} ${text}`);
    }
    return r.json();
  });
}

/** Chat — attach a remote URL (yt-dlp on the backend). Same response shape. */
export function attachChatUrl(sessionId, url) {
  return jfetch(`/chat/sessions/${sessionId}/attach/url`, {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

/** Chat — transcribe a recorded mic blob locally (faster-whisper turbo,
 *  worship-domain prompt). Audio never leaves the local backend. */
export function transcribeChatVoice(sessionId, blob, locale = "ko") {
  const fd = new FormData();
  fd.append("audio", blob, "voice.webm");
  fd.append("locale", locale);
  return fetch(
    `${API_BASE}/chat/sessions/${sessionId}/voice`,
    { method: "POST", body: fd },
  ).then(async (r) => {
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      throw new Error(`${r.status} ${text}`);
    }
    return r.json();
  });
}

/** Pull the FastAPI ``{detail: ...}`` message off a non-ok response. */
async function _errorDetail(resp) {
  try {
    const j = await resp.clone().json();
    return typeof j?.detail === "string" ? j.detail : "";
  } catch {
    return "";
  }
}

/** Probe whether an artifact can still be played/downloaded. Returns a
 *  user-facing Korean message when it's gone (410 = retention-expired) or
 *  otherwise unavailable, else ``null``. Uses a 1-byte Range so it never
 *  pulls the whole file just to check. */
export async function artifactUnavailableReason(jobId, kind) {
  try {
    const r = await fetch(`${API_BASE}/jobs/${jobId}/download/${kind}`, {
      headers: { Range: "bytes=0-0" },
    });
    if (r.ok || r.status === 206) return null;
    if (r.status === 410) {
      return (await _errorDetail(r)) ||
        "이 음원은 보존기간(기본 30일)이 지나 삭제되었어요. 다시 변환해주세요.";
    }
    if (r.status === 404) return "음원을 찾을 수 없어요. 다시 변환해주세요.";
    return `재생할 수 없어요 (오류 ${r.status}).`;
  } catch {
    return "재생 실패: 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.";
  }
}

/** Download an artifact. On Chrome/Edge opens the native save dialog so the
 *  user can pick the destination folder + filename.
 *
 *  Pre-flights the request so an expired artifact (HTTP 410, past the 30-day
 *  retention window) raises a friendly toast instead of saving a JSON error
 *  body or silently failing. */
export async function downloadArtifact(jobId, kind, suggestedName) {
  const url = `${API_BASE}/jobs/${jobId}/download/${kind}`;

  let resp;
  try {
    resp = await fetch(url);
  } catch {
    toast.error("다운로드 실패: 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.");
    return;
  }
  if (!resp.ok) {
    const detail = await _errorDetail(resp);
    toast.error(
      resp.status === 410
        ? (detail || "이 음원은 보존기간(기본 30일)이 지나 삭제되었어요. 다시 변환해주세요.")
        : `다운로드 실패 (오류 ${resp.status})${detail ? ` — ${detail}` : ""}`,
    );
    return;
  }

  // Chrome/Edge: stream straight into the user-chosen file.
  if (typeof window.showSaveFilePicker === "function") {
    try {
      const ext = suggestedName.includes(".") ? suggestedName.split(".").pop() : "bin";
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: "Audio file", accept: { "audio/*": [`.${ext}`] } }],
      });
      const writable = await handle.createWritable();
      await resp.body.pipeTo(writable);
      return;
    } catch (e) {
      if (e.name === "AbortError") return; // user cancelled the save dialog
      // otherwise fall through to the anchor/blob path below
    }
  }

  // Fallback: buffer to a blob so a cross-origin (R2) redirect still saves
  // with the suggested filename instead of navigating to the object.
  try {
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = suggestedName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
  } catch {
    toast.error("다운로드 저장 중 오류가 발생했어요.");
  }
}
