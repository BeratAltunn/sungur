import type {
  ChatTurn,
  Decision,
  EvidencePacket,
  FrameResponse,
  FrameTracks,
  Health,
  Level,
  MapContext,
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

export const api = {
  health: () => http<Health>("/api/health"),
  summary: () => http<ShiftSummary>("/api/summary"),
  triage: () => http<TriageRow[]>("/api/triage"),
  map: () => http<MapContext>("/api/map"),
  frame: (id: string) => http<FrameResponse>(`/api/frames/${id}`),
  packet: (id: string) => http<EvidencePacket>(`/api/frames/${id}/packet`),
  tracks: (id: string) => http<FrameTracks>(`/api/frames/${id}/tracks`),
  trace: (runId: string) => http<TraceStep[]>(`/api/runs/${runId}/trace`),
  imageUrl: (id: string) => `/api/frames/${id}/image`,
  evaluate: (id: string, live: boolean) =>
    http<FrameResponse>(`/api/frames/${id}/evaluate?live=${live}`, { method: "POST" }),
  chat: (question: string, history: { role: string; content: string }[], imageId: string | null) =>
    http<ChatTurn>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question, history, image_id: imageId }),
    }),
  decide: (id: string, body: { run_id: string; action: Decision["action"]; level?: Level; reason?: string }) =>
    http<{ decision: Decision | null }>(`/api/frames/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
