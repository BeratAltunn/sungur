import { useCallback, useEffect, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { SummaryContext } from "./components/ui";
import { api } from "./lib/api";
import { storage } from "./lib/format";
import type { Health, ShiftSummary, TriageRow, VehicleFocus } from "./lib/types";
import { DRAG_TYPE, readDrag } from "./lib/vehicles";
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
  // A vehicle in the chat's focus (dragged in, or "Sor" on a vehicle chip) and the queue's selected frame.
  const [chatFocus, setChatFocus] = useState<VehicleFocus | null>(null);
  const [triageSel, setTriageSel] = useState<string | null>(null);
  const focusVehicle = useCallback(
    (f: VehicleFocus) => {
      setChatFocus(f);
      toggleChat(true);
    },
    [toggleChat],
  );
  useEffect(() => {
    const on = (e: Event) => focusVehicle((e as CustomEvent<VehicleFocus>).detail);
    window.addEventListener("sentinel:chat-focus", on);
    return () => window.removeEventListener("sentinel:chat-focus", on);
  }, [focusVehicle]);
  // The chat's frame: the open frame, or the queue's selected one. Opening another frame drops a vehicle focus
  // that belonged to a different frame.
  const routeFrame = route.page === "frame" || route.page === "brief" ? route.id : null;
  const pageFrame = routeFrame ?? (route.page === "triage" ? triageSel : null);
  useEffect(() => {
    if (routeFrame) setChatFocus((f) => (f && f.image_id !== routeFrame ? null : f));
  }, [routeFrame]);

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
        <button
          className="chat-fab btn btn-primary"
          onClick={() => toggleChat(true)}
          title="Sohbeti aç (/) · bir aracı buraya sürükleyerek de açabilirsiniz"
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault();
          }}
          onDrop={(e) => {
            const f = readDrag(e.dataTransfer);
            document.body.classList.remove("dragging-vehicle");
            if (f) focusVehicle(f);
          }}
        >
          Sohbet <kbd className="kbd">/</kbd>
        </button>
      )}
      <ChatPanel open={chatOpen} onClose={() => toggleChat(false)} imageId={pageFrame} focus={chatFocus} onFocus={setChatFocus} />
    </div>
    </SummaryContext.Provider>
  );
}
