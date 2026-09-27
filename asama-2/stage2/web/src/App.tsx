import { useCallback, useEffect, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { SummaryContext } from "./components/ui";
import { api } from "./lib/api";
import { storage } from "./lib/format";
import type { ChatItem, Health, ShiftSummary, TriageRow } from "./lib/types";
import { CHAT_ICON } from "./lib/symbols";
import { DRAG_TYPE, MAX_CONTEXT, endDrag, itemKey, readDrag } from "./lib/vehicles";
import { EscalationCard, HandoverPage } from "./pages/Handover";
import { FramePage } from "./pages/Frame";
import { ImpactPage } from "./pages/Impact";
import { LabelPage } from "./pages/Label";
import { TriagePage } from "./pages/Triage";

// Hash routing keeps the app a single static bundle served by FastAPI:
//   #/  ·  #/frame/img_000860  ·  #/label[/img_000860]  (blind gold-set labelling)
//   #/handover (shift handover)  ·  #/brief/img_000860 (printable escalation card for the duty officer)
//   #/impact (shift simulation: decision vs vehicles' arrival)
function useRoute() {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const m = hash.match(/^#\/frame\/([\w-]+)/);
  if (m) return { page: "frame" as const, id: m[1] };
  const b = hash.match(/^#\/brief\/([\w-]+)/);
  if (b) return { page: "brief" as const, id: b[1] };
  if (hash.startsWith("#/handover")) return { page: "handover" as const };
  if (hash.startsWith("#/impact")) return { page: "impact" as const };
  const l = hash.match(/^#\/label(?:\/([\w-]+))?/);
  if (l) return { page: "label" as const, id: l[1] ?? null };
  return { page: "triage" as const };
}

export const go = (path: string) => {
  window.location.hash = path;
};

export default function App() {
  const route = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [queue, setQueue] = useState<TriageRow[] | null>(null);
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [chatOpen, setChatOpen] = useState<boolean>(() => storage.get("chat_open", false));
  const toggleChat = useCallback((v?: boolean) => {
    setChatOpen((o) => {
      const next = v ?? !o;
      storage.set("chat_open", next);
      return next;
    });
  }, []);
  // What the operator put in the chat (dragged in, or "Sor"): vehicles and frames, oldest first, ≤ MAX_CONTEXT.
  // It survives page changes on purpose: comparing frames means collecting them from different screens.
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [triageSel, setTriageSel] = useState<string | null>(null);
  const addItem = useCallback(
    (item: ChatItem) => {
      setChatItems((xs) => (xs.some((x) => itemKey(x) === itemKey(item)) ? xs : [...xs, item].slice(-MAX_CONTEXT)));
      toggleChat(true);
    },
    [toggleChat],
  );
  useEffect(() => {
    const on = (e: Event) => addItem((e as CustomEvent<ChatItem>).detail);
    window.addEventListener("sentinel:chat-add", on);
    return () => window.removeEventListener("sentinel:chat-add", on);
  }, [addItem]);
  // The page's frame: the open frame, or the queue's selected one (the chat's context when nothing is added).
  const routeFrame = route.page === "frame" || route.page === "brief" ? route.id : null;
  const pageFrame = routeFrame ?? (route.page === "triage" ? triageSel : null);

  // "/" opens the chat from anywhere (outside text fields).
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT" && !window.location.hash.startsWith("#/label")) {
        e.preventDefault();
        toggleChat(true);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [toggleChat]);

  // Queue and summary (status bar posture, shift card) always refresh together.
  const refreshQueue = useCallback(() => {
    api.triage().then(setQueue).catch(() => undefined);
    api.summary().then(setSummary).catch(() => undefined);
  }, []);

  // Health (model / LLM / warm-up) is polled; the queue refreshes while the warm-up fills in LLM headlines.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const h = await api.health();
        if (!alive) return;
        setHealth((prev) => {
          if (!prev || prev.warmup.done !== h.warmup.done) refreshQueue();
          return h;
        });
      } catch {
        /* server restarting */
      }
    };
    tick();
    const id = window.setInterval(tick, 4000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [refreshQueue]);

  // Blind labelling: no chat (it could reveal the system's levels).
  if (route.page === "label") return <LabelPage id={route.id} health={health} />;

  return (
    <SummaryContext.Provider value={summary}>
    <div className={`shell ${chatOpen ? "chat-open" : ""}`}>
      {route.page === "frame" ? (
        <FramePage key={route.id} id={route.id} health={health} queue={queue} onChanged={refreshQueue} />
      ) : route.page === "brief" ? (
        <EscalationCard key={route.id} id={route.id} health={health} />
      ) : route.page === "handover" ? (
        <HandoverPage health={health} />
      ) : route.page === "impact" ? (
        <ImpactPage health={health} />
      ) : (
        <TriagePage health={health} queue={queue} onSelect={setTriageSel} />
      )}
      {!chatOpen && (
        // The chat lives at the side: an icon on the right edge (a drop target too), the panel opens there.
        <button
          className="chat-fab"
          onClick={() => toggleChat(true)}
          aria-label="Sohbet (/)"
          title="Sohbeti aç (/) · bir aracı ya da kareyi buraya sürükleyerek de açabilirsiniz"
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault();
          }}
          onDrop={(e) => {
            const item = readDrag(e.dataTransfer);
            endDrag();
            if (item) addItem(item);
          }}
        >
          <svg className="chat-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d={CHAT_ICON} />
          </svg>
        </button>
      )}
      <ChatPanel open={chatOpen} onClose={() => toggleChat(false)} imageId={pageFrame}
        items={chatItems}
        onAdd={addItem}
        onRemove={(key) => setChatItems((xs) => xs.filter((x) => itemKey(x) !== key))}
        onClear={() => setChatItems([])}
      />
    </div>
    </SummaryContext.Provider>
  );
}
