// REST + WS helpers for the Voice Agent UI.
const J = (r) => {
  if (!r.ok) return r.json().catch(() => ({})).then((e) => { throw new Error(e.detail || r.status); });
  return r.json();
};
const H = { "Content-Type": "application/json" };

export const api = {
  health: () => fetch("/api/health").then(J),
  config: () => fetch("/api/config").then(J),
  saveConfig: (b) => fetch("/api/config", { method: "POST", headers: H, body: JSON.stringify(b) }).then(J),
  suggestPrompt: (b) => fetch("/api/persona/suggest", { method: "POST", headers: H, body: JSON.stringify(b) }).then(J),

  data: () => fetch("/api/data").then(J),
  upload: (file) => { const fd = new FormData(); fd.append("file", file); return fetch("/api/data/upload", { method: "POST", body: fd }).then(J); },
  removeSource: (s) => fetch(`/api/data/${encodeURIComponent(s)}`, { method: "DELETE" }).then(J),
  reindex: () => fetch("/api/data/reindex", { method: "POST" }).then(J),

  sourceChunks: (s) => fetch(`/api/data/${encodeURIComponent(s)}/chunks`).then(J),
  sourceFileUrl: (s) => `/api/data/${encodeURIComponent(s)}/file`,
  search: (q, k = 8) => fetch(`/api/search?q=${encodeURIComponent(q)}&k=${k}`).then(J),

  logs: () => fetch("/api/logs").then(J),
  log: (id) => fetch(`/api/logs/${id}`).then(J),

  stats: () => fetch("/api/stats").then(J),
  sessions: () => fetch("/api/sessions").then(J),
  newSession: (title) => fetch("/api/sessions", { method: "POST", headers: H, body: JSON.stringify({ title }) }).then(J),
  session: (id) => fetch(`/api/sessions/${id}`).then(J),
  renameSession: (id, title) => fetch(`/api/sessions/${id}`, { method: "PATCH", headers: H, body: JSON.stringify({ title }) }).then(J),
  delSession: (id) => fetch(`/api/sessions/${id}`, { method: "DELETE" }).then(J),

  calls: () => fetch("/api/calls").then(J),
  call: (id) => fetch(`/api/calls/${id}`).then(J),
  newCall: (b) => fetch("/api/calls", { method: "POST", headers: H, body: JSON.stringify(b) }).then(J),
  uploadCallAudio: (id, blob) => { const fd = new FormData(); fd.append("file", blob, "rec.webm"); return fetch(`/api/calls/${id}/audio`, { method: "POST", body: fd }).then(J); },
  callAudioUrl: (id) => `/api/calls/${id}/audio`,
  delCall: (id) => fetch(`/api/calls/${id}`, { method: "DELETE" }).then(J),

  voices: () => fetch("/api/voices").then(J),
  voiceSampleUrl: (name) => `/api/voices/${encodeURIComponent(name)}/audio`,
  asr: (blob) => { const fd = new FormData(); fd.append("file", blob, "voice.webm"); return fetch("/api/asr", { method: "POST", body: fd }).then(J); },
  ttsUrl: () => "/api/tts",
  pageUrl: (p) => `/api/pages/${p}`,
};

// Streaming chat over WebSocket. Returns a controller with .send() and closes on done.
export function chatStream({ query, history, channel = "chat", session_id }, onEvent) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/chat`);
  ws.onopen = () => ws.send(JSON.stringify({ query, history, channel, session_id }));
  ws.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    onEvent(ev);
    if (ev.type === "done" || ev.type === "error") ws.close();
  };
  ws.onerror = () => onEvent({ type: "error", message: "connection error" });
  return ws;
}

export const TYPE_AR = { text: "نص", table: "جدول", image_caption: "صورة" };
export const CHANNEL_AR = { chat: "دردشة", voice: "صوت", livekit: "مكالمة" };
