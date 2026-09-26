import maplibregl, { type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection } from "geojson";
import { useEffect, useRef, useState } from "react";
import { storage } from "../lib/format";
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
      { id: "bg", type: "background", paint: { "background-color": "#0a0f15" } },
      ...(t?.layers ?? []),
      ...(basemap ? [{ id: "carto", type: "raster" as const, source: "carto", paint: { "raster-opacity": 0.55 } }] : []),
    ],
    ...t?.extra,
  };
}

interface Props {
  className?: string;
  /** Called once the style is loaded, and again after the basemap is toggled (style reset). */
  onReady: (map: MLMap) => void;
  initial: { center: [number, number]; zoom: number };
  /** Tiltable, rotatable plane (right-drag or Ctrl+drag; compass resets). Off: a flat, north-up map. */
  threeD?: { pitch: number; maxPitch: number };
  /** 3D ground (DEM + texture) when the tiles are installed (scripts/build_terrain.py); the operator can turn it off. */
  terrain?: boolean;
}

export function MapView({ className, onReady, initial, threeD, terrain }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;
  const [basemap, setBasemap] = useState<boolean>(() => storage.get("basemap", false));
  const [dem, setDem] = useState<TerrainManifest | null>(null); // installed tiles; null → no terrain toggle
  const [ground, setGround] = useState<boolean>(() => storage.get("terrain", true));

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
      map.addControl(new maplibregl.NavigationControl({ showCompass: !!threeD, visualizePitch: !!threeD }), "top-right");
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
      const m = map;
      m.on("load", () => readyRef.current(m));
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
      </div>
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
