// 3D terrain for a map: an elevation (DEM) surface draped with a texture. Display only: evidence positions come from
// the backend and assume flat ground; this never feeds back into them.
//
// Tiles are static files in public/terrain/, made by `python3 scripts/build_terrain.py`. No manifest there → no
// terrain, and the map stays exactly as before.
import type { LayerSpecification, SourceSpecification, StyleSpecification } from "maplibre-gl";

type Bounds = [number, number, number, number];
interface TileSet {
  bounds: Bounds;
  minzoom: number;
  maxzoom: number;
  attribution: string;
}
export interface TerrainManifest {
  dem: TileSet & { encoding: "terrarium" | "mapbox" };
  texture: (TileSet & { ext: string }) | null;
}

const ROOT = "/terrain";
/** The plateau around the base has gentle relief; a little exaggeration makes ridges and valleys readable. */
const EXAGGERATION = 1.5;

let manifest: Promise<TerrainManifest | null> | null = null;

/** Fetched once per page. Missing (or the SPA's index.html in its place) → null. */
export function loadTerrain(): Promise<TerrainManifest | null> {
  manifest ??= fetch(`${ROOT}/manifest.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((m) => (m?.dem?.bounds ? (m as TerrainManifest) : null))
    .catch(() => null);
  return manifest;
}

const dem = (t: TerrainManifest): SourceSpecification => ({
  type: "raster-dem",
  tiles: [`${ROOT}/dem/{z}/{x}/{y}.png`],
  tileSize: 256,
  encoding: t.dem.encoding,
  bounds: t.dem.bounds,
  minzoom: t.dem.minzoom,
  maxzoom: t.dem.maxzoom,
  attribution: t.dem.attribution,
});

/** Style parts to merge into a map style: sources, the ground layers (go right above the background) and the 3D
 *  surface. With imagery, it is dimmed so the markers stay the brightest thing on the map; without, the ground is
 *  coloured by height and shaded from the same DEM. */
export function terrainStyle(t: TerrainManifest): {
  sources: Record<string, SourceSpecification>;
  layers: LayerSpecification[];
  extra: Pick<StyleSpecification, "terrain" | "sky">;
} {
  const tx = t.texture;
  const sources: Record<string, SourceSpecification> = { "terrain-dem": dem(t) };
  let layers: LayerSpecification[];
  if (tx) {
    sources["terrain-texture"] = {
      type: "raster",
      tiles: [`${ROOT}/texture/{z}/{x}/{y}.${tx.ext}`],
      tileSize: 256,
      bounds: tx.bounds,
      minzoom: tx.minzoom,
      maxzoom: tx.maxzoom,
      attribution: tx.attribution,
    };
    layers = [
      {
        id: "terrain-texture",
        type: "raster",
        source: "terrain-texture",
        paint: { "raster-brightness-max": 0.5, "raster-saturation": -0.35, "raster-contrast": 0.1 },
      },
    ];
  } else {
    sources["terrain-shade"] = dem(t); // MapLibre renders better when hillshade and the 3D surface use separate sources
    layers = [
      {
        id: "terrain-relief",
        type: "color-relief",
        source: "terrain-shade",
        paint: {
          "color-relief-color": ["interpolate", ["linear"], ["elevation"], 700, "#15201b", 900, "#1f2b22", 1100, "#2e3326", 1400, "#453f2e"],
        },
      },
      {
        id: "terrain-hillshade",
        type: "hillshade",
        source: "terrain-shade",
        paint: { "hillshade-shadow-color": "#05080b", "hillshade-highlight-color": "#3a4a5c", "hillshade-exaggeration": 0.45 },
      },
    ];
  }
  return {
    sources,
    layers,
    extra: {
      terrain: { source: "terrain-dem", exaggeration: EXAGGERATION },
      sky: {
        "sky-color": "#0a0f15",
        "horizon-color": "#1a2633",
        "fog-color": "#0a0f15",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.5,
        "fog-ground-blend": 0.7,
        "atmosphere-blend": 0,
      },
    },
  };
}
