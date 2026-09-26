import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, explain } from "../lib/api";
import { LABEL_TR, LEVEL_ICON, dec, smooth, storage, zoneName } from "../lib/format";
import type { ChatItem, ChatTurn, Suggestion } from "../lib/types";
import { DRAG_TYPE, endDrag, itemKey, readDrag } from "../lib/vehicles";
import { RefText } from "./ui";

interface Msg {
  role: "user" | "assistant";
  content: string;
  turn?: ChatTurn;
  error?: boolean;
  imageId?: string | null;
  context?: string | null; // "V7 · T0122; img_006673": what was in the chat's context
}

const TOOL_TR: Record<string, string> = {
  list_frames: "kareleri listele",
  analyze_image: "kareyi incele",
  get_track: "araç geçmişi",
  find_reports: "rapor ara",
  zone_summary: "bölge özeti",
};

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

/** Short label of a context item, as it appears in the conversation. */
const itemLabel = (c: ChatItem) => (c.kind === "vehicle" ? `${c.ref}${c.track_id ? ` · ${c.track_id}` : ""}` : c.image_id);

/** Chat with the evidence: the questions offered change with the situation (what the operator put in the
 *  context, else the page's frame, else the queue) and with the last answer. */
export function ChatPanel({
  open,
  onClose,
  imageId,
  items,
  onAdd,
  onRemove,
  onClear,
}: {
  open: boolean;
  onClose: () => void;
  imageId: string | null;
  items: ChatItem[];
  onAdd: (item: ChatItem) => void;
  onRemove: (key: string) => void;
  onClear: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(() => storage.get<Msg[]>("chat", []));
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<number | null>(null); // start time
  const [elapsed, setElapsed] = useState(0);
  const [situation, setSituation] = useState<Suggestion[]>([]);
  const [dropping, setDropping] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // The page's frame stays the open one; with nothing open, the first item's frame is.
  const ctxImage = imageId ?? items[0]?.image_id ?? null;
  const ctxLabel = items.length ? items.map(itemLabel).join("; ") : null;
  const ctxKey = items.map(itemKey).join("|");

  useEffect(() => storage.set("chat", msgs.slice(-40)), [msgs]);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: smooth() });
  }, [msgs, pending]);
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open, ctxKey]);
  useEffect(() => {
    if (pending === null) return;
    const h = window.setInterval(() => setElapsed(Math.round((Date.now() - pending) / 1000)), 500);
    return () => window.clearInterval(h);
  }, [pending]);
  // Situation questions for the current context (rule-based on the server, no LLM call).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    api
      .suggestions(ctxImage, items)
      .then((r) => alive && setSituation(r.suggestions))
      .catch(() => alive && setSituation([]));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ctxImage, ctxKey]);

  const send = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || pending !== null) return;
      const history = msgs.filter((m) => !m.error).slice(-8).map(({ role, content }) => ({ role, content }));
      setMsgs((m) => [...m, { role: "user", content: q, imageId: ctxImage, context: ctxLabel }]);
      setInput("");
      setElapsed(0);
      setPending(Date.now());
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const turn = await api.chat(q, history, ctxImage, items, ctrl.signal);
        setMsgs((m) => [...m, { role: "assistant", content: turn.answer, turn, error: turn.note === "llm_hata" }]);
      } catch (e) {
        const content = ctrl.signal.aborted ? "Soru iptal edildi." : `Soru yanıtlanamadı. ${explain(e)}`;
        setMsgs((m) => [...m, { role: "assistant", content, error: true }]);
      } finally {
        abortRef.current = null;
        setPending(null);
      }
    },
    [msgs, pending, ctxImage, items, ctxLabel],
  );

  // Quick questions: the last answer's follow-ups (same context), else the situation questions; never one asked.
  const asked = new Set(msgs.filter((m) => m.role === "user").map((m) => m.content));
  const last = msgs[msgs.length - 1];
  const lastUser = [...msgs].reverse().find((m) => m.role === "user");
  const sameCtx = !!lastUser && (lastUser.imageId ?? null) === ctxImage && (lastUser.context ?? null) === ctxLabel;
  const followups = last?.role === "assistant" && sameCtx ? (last.turn?.followups ?? []) : [];
  const quick = (followups.length ? followups : situation).filter((s) => !asked.has(s.text)).slice(0, 4);

  // 1–4 asks a quick question (Alt+1–4 while typing, so a question may still start with a digit).
  useEffect(() => {
    if (!open) return;
    const on = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).tagName === "TEXTAREA" || (e.target as HTMLElement).tagName === "INPUT";
      const m = e.code.match(/^Digit([1-4])$/);
      if (!m || (typing && !e.altKey) || (!typing && (e.ctrlKey || e.metaKey))) return;
      const inChat = (e.target as HTMLElement).closest?.(".chat");
      if (!inChat && typing) return;
      const s = quick[Number(m[1]) - 1];
      if (!s) return;
      e.preventDefault();
      send(s.text);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [open, quick, send]);

  const lastQuestion = lastUser?.content;

  if (!open) return null;
  return (
    <aside
      className={`chat ${dropping ? "chat-dropping" : ""}`}
      aria-label="Sohbet"
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setDropping(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropping(false);
      }}
      onDrop={(e) => {
        const item = readDrag(e.dataTransfer);
        setDropping(false);
        endDrag();
        if (!item) return;
        e.preventDefault();
        onAdd(item);
      }}
    >
      <div className="chat-head">
        <b>Sohbet</b>
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
          <p className="muted chat-intro">
            Kareler, araçların geçmişi ve saha raporları hakkında sorun. Cevaptaki her sayı sistemin kayıtlarından gelir.
            Anormal bir aracı buraya sürükleyin: sorular o araca göre değişir.
          </p>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg msg-user">
              {(m.imageId || m.context) && (
                <span className="muted small mono">{m.context ?? m.imageId} · </span>
              )}
              {m.content}
            </div>
          ) : (
            <div key={i} className={`msg msg-bot ${m.error ? "msg-error" : ""}`}>
              {m.turn && m.turn.tool_calls.length > 0 && (
                <details className="tools">
                  <summary>
                    {m.turn.tool_calls.length} kayıt sorgusu · {dec(m.turn.duration_ms / 1000)} sn
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
                    : `Doğrulanamayan değerler: ${m.turn.unverified.slice(0, 4).join(", ")}. Teyit edin.`}
                </div>
              )}
              {m.error && i === msgs.length - 1 && lastQuestion && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setMsgs((x) => x.slice(0, -2));
                    send(lastQuestion);
                  }}
                >
                  Tekrar dene
                </button>
              )}
            </div>
          ),
        )}
        {pending !== null && (
          <div className="msg msg-bot msg-pending" role="status">
            <div>
              <span className="spinner" aria-hidden /> Kayıtları sorguluyor… {elapsed} sn
            </div>
            {elapsed >= 10 && (
              <>
                {/* > 10 s: a progress bar (indeterminate: the model's remaining time is not knowable, so none is shown) */}
                <div className="progress" role="progressbar" aria-label="Yanıt bekleniyor" aria-valuetext={`${elapsed} saniye`}>
                  <span />
                </div>
                <p className="muted small">
                  Yanıtlar genelde 10–25 sn sürer. Kanıt ekranda hazır; beklerken karede çalışmaya devam edebilirsiniz.
                </p>
              </>
            )}
            <button className="btn btn-ghost btn-sm" onClick={() => abortRef.current?.abort()}>
              İptal
            </button>
          </div>
        )}
        {pending === null && quick.length > 0 && (
          <div className="quick" aria-label={followups.length ? "Sıradaki sorular" : "Duruma göre sorular"}>
            <span className="quick-title">{followups.length ? "Sıradaki sorular" : "Duruma göre sorular"}</span>
            {quick.map((s, i) => (
              <button key={s.text} className="suggestion" onClick={() => send(s.text)}>
                <kbd className="kbd">{i + 1}</kbd>
                <span className="quick-text">{s.text}</span>
                <span className="quick-reason">{s.reason}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {dropping && <div className="chat-drop">Bırakın: sorular bağlamdaki öğelere göre değişir</div>}

      <div className="chat-context" aria-label="Sohbet bağlamı">
        <span className="muted small">Bağlam:</span>
        {items.length === 0 ? (
          <>
            <span className="ctx-pill mono">{ctxImage ?? "tüm kareler"}</span>
            <span className="muted small">araç ya da uyarı kartı sürükleyin (en fazla 4)</span>
          </>
        ) : (
          <>
            {items.map((c) => (
              <span key={itemKey(c)} className={`ctx-pill ctx-${c.kind}`}>
                {c.kind === "vehicle" ? (
                  <>
                    <b>{c.ref}</b> {LABEL_TR[c.label]}
                    {c.track_id && <span className="mono"> · {c.track_id}</span>}
                    <span className="muted mono"> · {c.image_id}</span>
                  </>
                ) : (
                  <>
                    <span aria-hidden>{LEVEL_ICON[c.level]}</span> <span className="mono">{c.image_id}</span>
                    <span className="muted"> · {zoneName(c.zone)} {c.capture_time}</span>
                  </>
                )}
                <button className="ctx-clear" onClick={() => onRemove(itemKey(c))} aria-label={`${itemLabel(c)} bağlamdan çıkar`}>
                  ✕
                </button>
              </span>
            ))}
            {items.length > 1 && (
              <button className="linklike" onClick={onClear}>
                hepsini çıkar
              </button>
            )}
          </>
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
          placeholder={
            items.length > 1
              ? "Bu öğeler hakkında sorun… (Alt+1–4: hazır soru)"
              : items.length === 1
                ? `${itemLabel(items[0])} hakkında sorun… (Alt+1–4: hazır soru)`
                : ctxImage
                  ? "Bu kare hakkında sorun… (Alt+1–4: hazır soru)"
                  : "Bir soru sorun… (Alt+1–4: hazır soru)"
          }
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
