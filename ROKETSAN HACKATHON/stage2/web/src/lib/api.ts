import type {
  ChatItem,
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
  Suggestion,
  TraceStep,
  TriageRow,
} from "./types";

/** Errors in operational terms: what happened, what still works, what to do. The HTTP code stays at the end
 *  for whoever reads the server log. Validation messages from the service (e.g. "gerekçe zorunlu") pass through. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly recovery: string,
    readonly code: number | null,
  ) {
    super(message);
  }
}

/** One line for toasts and inline messages: what happened + what to do. */
export const explain = (e: unknown) =>
  e instanceof ApiError ? `${e.message} ${e.recovery}` : String((e as Error)?.message ?? e);

const OFFLINE = new ApiError(
  "Değerlendirme servisine ulaşılamıyor.",
  "Ekrandaki bilgiler geçerli kalır. Sunucuyu başlatın (make app ya da docker compose up -d), sonra Tekrar dene.",
  null,
);

function operational(status: number, detail: string | null): ApiError {
  if (status === 404) return new ApiError(detail ?? "İstenen kayıt bulunamadı.", "Kare kimliğini kontrol edin ya da kuyruğa dönün.", status);
  if (status === 422 || status === 400) return new ApiError(detail ?? "Girilen bilgi eksik ya da geçersiz.", "Alanı düzeltip tekrar gönderin.", status);
  if (status === 503) return new ApiError("Servis başlatılıyor.", "Birkaç saniye sonra Tekrar dene.", status);
  return new ApiError(
    "Servis bu isteği tamamlayamadı.",
    "Diğer ekranlar çalışmaya devam eder. Tekrar dene; sürerse sunucu günlüğüne bakın (docker compose logs).",
    status,
  );
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw OFFLINE;
  }
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw operational(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Reads an NDJSON stream line by line; errors thrown by onEvent abort the read. */
async function ndjson(path: string, init: RequestInit, onEvent: (ev: LiveEvent) => void): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw OFFLINE;
  }
  if (!res.ok || !res.body) throw operational(res.status, null);
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

/** What the backend needs of a chat item (it resolves tracks and levels itself). */
const wire = (c: ChatItem) => (c.kind === "vehicle" ? { kind: c.kind, image_id: c.image_id, ref: c.ref } : { kind: c.kind, image_id: c.image_id });

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
  chat: (
    question: string,
    history: { role: string; content: string }[],
    imageId: string | null,
    context: ChatItem[],
    signal?: AbortSignal,
  ) =>
    http<ChatTurn>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question, history, image_id: imageId, context: context.map(wire) }),
      signal,
    }),
  /** Questions for the situation: what is in the chat's context, else the frame, else the queue. */
  suggestions: (imageId: string | null, context: ChatItem[]) =>
    context.length
      ? http<{ suggestions: Suggestion[] }>("/api/chat/suggestions", {
          method: "POST",
          body: JSON.stringify({ image_id: imageId, context: context.map(wire) }),
        })
      : http<{ suggestions: Suggestion[] }>(`/api/chat/suggestions${imageId ? `?image_id=${imageId}` : ""}`),
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
