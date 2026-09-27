import { useEffect, useRef, useState } from "react";
import { storage } from "../lib/format";

export interface LayerDef<K extends string> {
  key: K;
  label: string;
}

/** Map layers the operator can switch off to see only what matters now. Persisted per map. */
export function useLayers<K extends string>(storageKey: string, defaults: Record<K, boolean>) {
  const [layers, setLayers] = useState<Record<K, boolean>>(() => ({ ...defaults, ...storage.get(storageKey, {}) }));
  const toggle = (k: K) =>
    setLayers((l) => {
      const next = { ...l, [k]: !l[k] };
      storage.set(storageKey, next);
      return next;
    });
  return { layers, toggle };
}

/** "Katmanlar" button with a checklist; closes on Esc or a click outside. */
export function LayerMenu<K extends string>({
  defs,
  layers,
  onToggle,
}: {
  defs: LayerDef<K>[];
  layers: Record<K, boolean>;
  onToggle: (k: K) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const off = defs.filter((d) => !layers[d.key]).length;
  return (
    <div className="layer-menu" ref={ref}>
      <button className="map-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Katmanlar{off ? ` · ${off} kapalı` : ""}
      </button>
      {open && (
        <ul className="layer-list" aria-label="Harita katmanları">
          {defs.map((d) => (
            <li key={d.key}>
              <label className="check">
                <input type="checkbox" checked={layers[d.key]} onChange={() => onToggle(d.key)} />
                {d.label}
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
