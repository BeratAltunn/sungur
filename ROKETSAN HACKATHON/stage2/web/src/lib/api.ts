import type {
  ChatTurn,
  Decision,
  EvidencePacket,
  FrameResponse,
  FrameTracks,
  Health,
  ImpactReport,
  Level,
  LiveEvent,
  MapContext,
  ShiftHandover,
  ShiftSummary,
  TraceStep,
  TriageRow,
} from "./types";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

/** Reads an NDJSON stream line by line; errors thrown by onEvent abort the read. */
async function ndjson(path: string, init: RequestInit, onEvent: (ev: LiveEvent) => void): Promise<void> {
  const res = await fetch(path, init);
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    buf += decoder.decode(value, { stream: !done });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as LiveEvent);
    }
    if (done) break;
  }
}

export const api = {
  health: () => http<Health>("/api/health"),
  summary: () => http<ShiftSummary>("/api/summary"),
  handover: () => http<ShiftHandover>("/api/handover"),
  impact: () => http<ImpactReport>("/api/impact"),
  triage: () => http<TriageRow[]>("/api/triage"),
  map: () => http<MapContext>("/api/map"),
  frame: (id: string) => http<FrameResponse>(`/api/frames/${id}`),
  packet: (id: string) => http<EvidencePacket>(`/api/frames/${id}/packet`),
  tracks: (id: string) => http<FrameTracks>(`/api/frames/${id}/tracks`),
  trace: (runId: string) => http<TraceStep[]>(`/api/runs/${runId}/trace`),
  imageUrl: (id: string) => `/api/frames/${id}/image`,
  evaluate: (id: string, live: boolean) =>
    http<FrameResponse>(`/api/frames/${id}/evaluate?live=${live}`, { method: "POST" }),
  /** Same run, streamed: step start/end, the packet after step 5, then the result. */
  evaluateStream: (id: string, live: boolean, onEvent: (ev: LiveEvent) => void) =>
    ndjson(`/api/frames/${id}/evaluate/stream?live=${live}`, { method: "POST" }, onEvent),
  chat: (question: string, history: { role: string; content: string }[], imageId: string | null, signal?: AbortSignal) =>
    http<ChatTurn>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question, history, image_id: imageId }),
      signal,
    }),
  goldProgress: (labeler: string) =>
    http<{ labeler: string; done: Record<string, Level>; order: string[]; total: number }>(
      `/api/gold/${encodeURIComponent(labeler)}`,
    ),
  gold: (id: string, body: { labeler: string; level: Level; note?: string }) =>
    http<{ image_id: string; labeler: string; level: Level; at: string }>(`/api/frames/${id}/gold`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** The operator opened a frame: start of the measured handling time. */
  viewed: (id: string) => http<{ at: string }>(`/api/frames/${id}/viewed`, { method: "POST" }),
  decide: (id: string, body: { run_id: string; action: Decision["action"]; level?: Level; reason?: string }) =>
    http<{ decision: Decision | null }>(`/api/frames/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
