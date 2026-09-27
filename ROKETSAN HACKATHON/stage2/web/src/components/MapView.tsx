import maplibregl, { type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { storage } from "../lib/format";
import { token } from "../lib/theme";
import { loadTerrain, terrainStyle, type TerrainManifest } from "../lib/terrain";

// No glyphs/sprites: the map works offline. Text is drawn with HTML markers.
function style(basemap: boolean, terrain: TerrainManifest | null): StyleSpecification {
  const t = terrain ? terrainStyle(terrain) : null;
  return {
    version: 8,
    sources: {
      ...t?.sources,
      ...(basemap && {
        carto: {
          type: "raster",
          tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap katkıcıları © CARTO",
        },
      }),
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": token("--bg") } },
      ...(t?.layers ?? []),
      ...(basemap ? [{ id: "carto", type: "raster" as const, source: "carto", paint: { "raster-opacity": 0.55 } }] : []),
    ],
    ...t?.extra,
  };
}

/** Maps open tilted; right-drag / Ctrl+drag re-orients the plane, the compass resets it. Shared by the main map
 *  and the frame maps so both look and handle the same. */
export const MAP_3D = { pitch: 45, maxPitch: 70 };

interface Props {
  className?: string;
  /** Called once the style is loaded, and again after the basemap is toggled (style reset). */
  onReady: (map: MLMap) => void;
  initial: { center: [number, number]; zoom: number; bearing?: number };
  /** Tiltable, rotatable plane (right-drag or Ctrl+drag; compass resets). Off: a flat, north-up map. */
  threeD?: { pitch: number; maxPitch: number };
  /** 3D ground (DEM + texture) when the tiles are installed (scripts/build_terrain.py); the operator can turn it off. */
  terrain?: boolean;
  /** Extra controls next to the basemap / ground toggles (e.g. the layer menu). */
  controls?: ReactNode;
}

export function MapView({ className, onReady, initial, threeD, terrain, controls }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const [basemap, setBasemap] = useState<boolean>(() => storage.get("basemap", false));
  const [dem, setDem] = useState<TerrainManifest | null>(null); // installed tiles; null → no terrain toggle
  const [ground, setGround] = useState<boolean>(() => storage.get("terrain", true));
  const [bearing, setBearing] = useState(initial.bearing ?? 0);
  const [pitch, setPitch] = useState(threeD?.pitch ?? 0);

  useEffect(() => {
    let map: MLMap | null = null;
    let gone = false;
    // Terrain is part of the style (not added afterwards), so a basemap switch doesn't drop it. The manifest is a
    // small local file; waiting for it avoids building the map twice.
    (terrain ? loadTerrain() : Promise.resolve(null)).then((t) => {
      if (gone || !el.current) return;
      setDem(t);
      map = new maplibregl.Map({
        container: el.current,
        style: style(basemap, ground ? t : null),
        center: initial.center,
        zoom: initial.zoom,
        attributionControl: { compact: true },
        dragRotate: !!threeD,
        pitchWithRotate: !!threeD,
        touchPitch: !!threeD,
        pitch: threeD?.pitch ?? 0,
        maxPitch: threeD?.maxPitch ?? 0,
      });
      if (!threeD) map.touchZoomRotate.disableRotation();
      // Zoom buttons only: the compass is our own HUD rose (bottom-right, off the evidence).
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
      const m = map;
      m.on("load", () => readyRef.current(m));
      m.on("rotate", () => setBearing(m.getBearing()));
      m.on("pitch", () => setPitch(m.getPitch()));
      mapRef.current = m;
    });
    return () => {
      gone = true;
      map?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function restyle(nextBasemap: boolean, nextGround: boolean) {
    const map = mapRef.current;
    if (!map) return;
    // MapLibre cannot diff terrain away (it logs and rebuilds anyway), so a terrain switch rebuilds directly.
    map.setStyle(style(nextBasemap, nextGround ? dem : null), { diff: nextGround === ground });
    map.once("styledata", () => readyRef.current(map));
  }
  function toggleBasemap() {
    setBasemap(!basemap);
    storage.set("basemap", !basemap);
    restyle(!basemap, ground);
  }
  function toggleGround() {
    setGround(!ground);
    storage.set("terrain", !ground);
    restyle(basemap, !ground);
  }

  return (
    <div className={`map-wrap ${className ?? ""}`}>
      <div ref={el} className="map" />
      <div className="map-toggles">
        <button className="map-toggle" onClick={toggleBasemap} title="Altlık harita internet gerektirir">
          {basemap ? "Altlık: açık" : "Altlık: kapalı"}
        </button>
        {dem && (
          <button className="map-toggle" onClick={toggleGround} title="3B arazi ve uydu dokusu (yalnızca görsel; konumlar düz zemine göre hesaplanır)">
            {ground ? "Arazi: açık" : "Arazi: kapalı"}
          </button>
        )}
        {controls}
      </div>
      {threeD && (
        <Compass bearing={bearing} pitch={pitch} onReset={() => mapRef.current?.easeTo({ bearing: 0, pitch: 0, duration: 400 })} />
      )}
    </div>
  );
}

/** Compass rose fixed to the map's corner (screen space), so it never covers a vehicle or a track. It turns with the
 *  map; clicking it puts north back up and lays the map flat (top-down). Letters: K(uzey), D(oğu), G(üney), B(atı). */
function Compass({ bearing, pitch, onReset }: { bearing: number; pitch: number; onReset: () => void }) {
  const deg = Math.round(((bearing % 360) + 360) % 360) % 360;
  const reset = deg !== 0 || Math.round(pitch) !== 0;
  const where = deg ? `harita ${deg}° dönük` : "kuzey yukarıda";
  return (
    <button
      type="button"
      className="map-compass"
      onClick={onReset}
      title={reset ? `Kuzeyi yukarı al, düz görünüm (${where})` : "Kuzey yukarıda"}
      aria-label={reset ? `Pusula: ${where}; kuzeyi yukarı al ve düz görünüme dön` : "Pusula: kuzey yukarıda"}
    >
      <svg viewBox="-30 -30 60 60" aria-hidden="true" style={{ transform: `rotate(${-bearing}deg)` }}>
        <circle className="rose-ring" r="27" />
        <path className="rose-n" d="M0,-21 L5,0 L-5,0 Z" />
        <path className="rose-s" d="M0,21 L5,0 L-5,0 Z" />
        <text className="rose-k" y="-15.5" x="0">K</text>
        <text y="23" x="0">G</text>
        <text y="3.8" x="19.5">D</text>
        <text y="3.8" x="-19.5">B</text>
      </svg>
    </button>
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

/** HTML marker whose element is fully controlled by the caller. `onGround` lays it on the map plane (it tilts and
 *  rotates with the map, e.g. a heading arrow); otherwise it stays upright facing the viewer. */
export function htmlMarker(
  map: MLMap,
  lngLat: [number, number],
  html: string,
  className: string,
  onClick?: () => void,
  onGround = false,
) {
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
  const align = onGround ? "map" : "viewport";
  // opacityWhenCovered: a marker behind a ridge stays fully visible; the terrain is decoration, never a reason to hide evidence.
  return new maplibregl.Marker({ element: node, pitchAlignment: align, rotationAlignment: align, opacityWhenCovered: 1 })
    .setLngLat(lngLat)
    .addTo(map);
}
