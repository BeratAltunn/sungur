import maplibregl, { type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { useEffect, useRef, useState } from "react";
import { storage } from "../lib/format";

// No glyphs/sprites: the map works offline. Text is drawn with HTML markers.
function style(basemap: boolean): StyleSpecification {
  return {
    version: 8,
    sources: basemap
      ? {
          carto: {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap katkıcıları © CARTO",
          },
        }
      : {},
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0a0f15" } },
      ...(basemap ? [{ id: "carto", type: "raster" as const, source: "carto", paint: { "raster-opacity": 0.55 } }] : []),
    ],
  };
}

interface Props {
  className?: string;
  /** Called once the style is loaded, and again after the basemap is toggled (style reset). */
  onReady: (map: MLMap) => void;
  initial: { center: [number, number]; zoom: number };
}

export function MapView({ className, onReady, initial }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const [basemap, setBasemap] = useState<boolean>(() => storage.get("basemap", false));

  useEffect(() => {
    if (!el.current) return;
    const map = new maplibregl.Map({
      container: el.current,
      style: style(basemap),
      center: initial.center,
      zoom: initial.zoom,
      attributionControl: { compact: true },
      dragRotate: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => readyRef.current(map));
    mapRef.current = map;
    return () => map.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle() {
    const next = !basemap;
    setBasemap(next);
    storage.set("basemap", next);
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(style(next));
    map.once("styledata", () => readyRef.current(map));
  }

  return (
    <div className={`map-wrap ${className ?? ""}`}>
      <div ref={el} className="map" />
      <button className="map-toggle" onClick={toggle} title="Altlık harita internet gerektirir">
        {basemap ? "Altlık: açık" : "Altlık: kapalı"}
      </button>
    </div>
  );
}

/** Add or replace a GeoJSON source's data. */
export function setGeo(map: MLMap, id: string, data: FeatureCollection) {
  const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(data);
  else map.addSource(id, { type: "geojson", data });
}

export const fc = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
export const line = (coords: [number, number][], props: Record<string, unknown> = {}): Feature => ({
  type: "Feature",
  properties: props,
  geometry: { type: "LineString", coordinates: coords },
});
export const polygon = (coords: [number, number][], props: Record<string, unknown> = {}): Feature => ({
  type: "Feature",
  properties: props,
  geometry: { type: "Polygon", coordinates: [coords] },
});

/** HTML marker whose element is fully controlled by the caller. */
export function htmlMarker(map: MLMap, lngLat: [number, number], html: string, className: string, onClick?: () => void) {
  const node = document.createElement("div");
  node.className = className;
  node.innerHTML = html;
  if (onClick) {
    node.style.cursor = "pointer";
    node.addEventListener("click", (e) => {
      e.stopPropagation();
      onClick();
    });
  }
  return new maplibregl.Marker({ element: node }).setLngLat(lngLat).addTo(map);
}
