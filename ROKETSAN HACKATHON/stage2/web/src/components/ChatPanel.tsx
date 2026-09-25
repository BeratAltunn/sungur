import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { dec, smooth, storage } from "../lib/format";
import type { ChatTurn } from "../lib/types";
import { RefText } from "./ui";

interface Msg {
  role: "user" | "assistant";
  content: string;
  turn?: ChatTurn;
  error?: boolean;
  imageId?: string | null;
}

const TOOL_TR: Record<string, string> = {
  list_frames: "kareleri listele",
  analyze_image: "kareyi incele",
  get_track: "araç geçmişi",
  find_reports: "rapor ara",
  zone_summary: "bölge özeti",
};

const GENERAL = [
  "En riskli 3 kare hangileri ve neden?",
  "T0122 12:35'te neredeydi?",
  "12:00–13:00 arasında hangi resmî raporlar kanıtla çelişiyor?",
  "Doğu Yolu bölgesinde gün boyu kaç ağır araç görüldü?",
];
const IN_FRAME = ["Bu karedeki en riskli araç neden riskli?", "Bu karenin hangi raporları çelişiyor ve neden?"];

/** Evidence chips in answers: frame ids navigate, V/T/R ids are handed to the open frame page. */
export function emitRef(id: string) {
  if (id.startsWith("img_")) window.location.hash = `/frame/${id}`;
  else window.dispatchEvent(new CustomEvent("sentinel:ref", { detail: id }));
}

/** Minimal markdown: paragraphs, "- " lists and **bold**; ids become chips. */
function Rich({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length)
      blocks.push(
        <ul key={blocks.length}>
          {list.map((l, i) => (
            <li key={i}>
              <Inline text={l} />
            </li>
          ))}
        </ul>,
      );
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (/^[-*•]\s+/.test(line)) list.push(line.replace(/^[-*•]\s+/, ""));
    else {
      flush();
      if (line) blocks.push(<p key={blocks.length}><Inline text={line} /></p>);
    }
  }
  flush();
  return <>{blocks}</>;
}

function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>
            <RefText text={part.slice(2, -2)} onRef={emitRef} />
          </strong>
        ) : (
          <RefText key={i} text={part} onRef={emitRef} />
        ),
      )}
    </>
  );
}

export function ChatPanel({ open, onClose, imageId }: { open: boolean; onClose: () => void; imageId: string | null }) {
  const [msgs, setMsgs] = useState<Msg[]>(() => storage.get<Msg[]>("chat", []));
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<number | null>(null); // start time
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => storage.set("chat", msgs.slice(-40)), [msgs]);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: smooth() });
  }, [msgs, pending]);
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);
  useEffect(() => {
    if (pending === null) return;
    const h = window.setInterval(() => setElapsed(Math.round((Date.now() - pending) / 1000)), 500);
    return () => window.clearInterval(h);
  }, [pending]);

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || pending !== null) return;
    const history = msgs.filter((m) => !m.error).slice(-8).map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: q, imageId }]);
    setInput("");
    setElapsed(0);
    setPending(Date.now());
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const turn = await api.chat(q, history, imageId, ctrl.signal);
      setMsgs((m) => [...m, { role: "assistant", content: turn.answer, turn, error: turn.note === "llm_hata" }]);
    } catch (e) {
      const content = ctrl.signal.aborted ? "Soru iptal edildi." : `İstek başarısız: ${(e as Error).message}`;
      setMsgs((m) => [...m, { role: "assistant", content, error: true }]);
    } finally {
      abortRef.current = null;
      setPending(null);
    }
  };

  // Suggestions not asked yet: shown when the chat is empty and as follow-ups under the last answer.
  const asked = new Set(msgs.filter((m) => m.role === "user").map((m) => m.content));
  const suggestions = (imageId ? [...IN_FRAME, ...GENERAL.slice(1, 3)] : GENERAL).filter((s) => !asked.has(s));

  const lastQuestion = [...msgs].reverse().find((m) => m.role === "user")?.content;

  if (!open) return null;
  return (
    <aside className="chat" aria-label="Sohbet">
      <div className="chat-head">
        <div>
          <b>Sohbet</b>
          <span className="muted small"> · {imageId ? `bağlam: ${imageId}` : "tüm veri"}</span>
        </div>
        <div className="chat-head-actions">
          {msgs.length > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={() => setMsgs([])} title="Konuşmayı temizle">
              Temizle
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Kapat">
            ✕
          </button>
        </div>
      </div>

      <div className="chat-list" ref={listRef} role="log" aria-live="polite" aria-label="Sohbet geçmişi">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <p className="muted">
              Kareler, araçların geçmişi ve saha raporları hakkında soru sorun. Cevaptaki her sayı sistemin kayıtlarından gelir;
              kimliklere tıklayarak kanıtı açabilirsiniz.
            </p>
            {suggestions.map((s) => (
              <button key={s} className="suggestion" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg msg-user">
              {m.imageId && <span className="muted small mono">{m.imageId} · </span>}
              {m.content}
            </div>
          ) : (
            <div key={i} className={`msg msg-bot ${m.error ? "msg-error" : ""}`}>
              {m.turn && m.turn.tool_calls.length > 0 && (
                <details className="tools">
                  <summary>
                    🔧 {m.turn.tool_calls.length} kayıt sorgusu · {dec(m.turn.duration_ms / 1000)} sn
                  </summary>
                  <ul>
                    {m.turn.tool_calls.map((c, j) => (
                      <li key={j} className={c.error ? "err" : ""}>
                        <span className="mono">
                          {c.name}({Object.entries(c.arguments).map(([k, v]) => `${k}=${v}`).join(", ")})
                        </span>{" "}
                        <span className="muted">
                          {TOOL_TR[c.name] ?? ""} → {c.error ?? c.summary}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <div className="msg-body">
                <Rich text={m.content} />
              </div>
              {m.turn && !m.error && (
                <div className={`grounding ${m.turn.grounded ? "g-ok" : "g-warn"}`}>
                  {m.turn.grounded
                    ? "✓ Sayılar kayıtlarla doğrulandı"
                    : `⚠ Doğrulanamayan değerler: ${m.turn.unverified.slice(0, 4).join(", ")}. Teyit edin.`}
                </div>
              )}
              {m.error && i === msgs.length - 1 && lastQuestion && (
                <button className="btn btn-ghost btn-sm" onClick={() => {
                  setMsgs((x) => x.slice(0, -2));
                  send(lastQuestion);
                }}>
                  Tekrar dene
                </button>
              )}
            </div>
          ),
        )}
        {pending === null && msgs.length > 0 && msgs[msgs.length - 1].role === "assistant" && suggestions.length > 0 && (
          <div className="followups" aria-label="Önerilen sorular">
            {suggestions.slice(0, 2).map((s) => (
              <button key={s} className="suggestion suggestion-sm" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {pending !== null && (
          <div className="msg msg-bot msg-pending" role="status">
            <div>
              <span className="spinner" aria-hidden /> Kayıtları sorguluyor… {elapsed} sn
            </div>
            {elapsed >= 10 && (
              <p className="muted small">
                Yanıtlar 5–45 sn sürebilir. Kanıt ekranda hazır; beklerken karede çalışmaya devam edebilirsiniz.
              </p>
            )}
            <button className="btn btn-ghost btn-sm" onClick={() => abortRef.current?.abort()}>
              İptal
            </button>
          </div>
        )}
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          ref={inputRef}
          rows={2}
          value={input}
          placeholder={imageId ? "Bu kare hakkında sorun…" : "Bir soru sorun…"}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            } else if (e.key === "Escape") onClose();
          }}
          aria-label="Soru"
        />
        <button className="btn btn-primary" disabled={!input.trim() || pending !== null}>
          Sor
        </button>
      </form>
    </aside>
  );
}
