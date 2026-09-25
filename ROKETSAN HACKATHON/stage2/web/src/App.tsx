import { useCallback, useEffect, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { api } from "./lib/api";
import { storage } from "./lib/format";
import type { Health, TriageRow } from "./lib/types";
import { FramePage } from "./pages/Frame";
import { LabelPage } from "./pages/Label";
import { TriagePage } from "./pages/Triage";

// Hash routing keeps the app a single static bundle served by FastAPI:
//   #/  ·  #/frame/img_000860  ·  #/label[/img_000860]  (blind gold-set labelling)
function useRoute() {
  const [hash, setHash] = useState(() => window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const m = hash.match(/^#\/frame\/([\w-]+)/);
  if (m) return { page: "frame" as const, id: m[1] };
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
  const [chatOpen, setChatOpen] = useState<boolean>(() => storage.get("chat_open", false));
  const toggleChat = useCallback((v?: boolean) => {
    setChatOpen((o) => {
      const next = v ?? !o;
      storage.set("chat_open", next);
      return next;
    });
  }, []);

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

  const refreshQueue = useCallback(() => {
    api.triage().then(setQueue).catch(() => undefined);
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
    <div className={`shell ${chatOpen ? "chat-open" : ""}`}>
      {route.page === "frame" ? (
        <FramePage key={route.id} id={route.id} health={health} queue={queue} onChanged={refreshQueue} />
      ) : (
        <TriagePage health={health} queue={queue} />
      )}
      {!chatOpen && (
        <button className="chat-fab btn btn-primary" onClick={() => toggleChat(true)} title="Sohbeti aç (/)">
          💬 Sohbet <kbd className="kbd">/</kbd>
        </button>
      )}
      <ChatPanel open={chatOpen} onClose={() => toggleChat(false)} imageId={route.page === "frame" ? route.id : null} />
    </div>
  );
}
