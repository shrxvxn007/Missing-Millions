// Web-Mercator tile math for cropping an ArcGIS World Imagery chip around a
// candidate centroid. Uses the same public no-key tile service as the basemap.
// Tile responses are stored durably in the Cache API after the first view, so
// chips keep workin later (and offline) without a service worker.
const CHIP_CACHE = "mm-esri-imagery-chips";

export async function loadChipTile(url: string): Promise<{ blobUrl: string | null; fromCache: boolean }> {
  if (typeof caches !== "undefined") {
    try {
      const cache = await caches.open(CHIP_CACHE);
      const hit = await cache.match(url);
      if (hit) {
        return { blobUrl: URL.createObjectURL(await hit.blob()), fromCache: true };
      }
    } catch {
      // Storage quota or private mode; fall through to the network path.
    }
  }
  try {
    const response = await fetch(url);
    if (response.ok) {
      if (typeof caches !== "undefined") {
        try {
          const cache = await caches.open(CHIP_CACHE);
          await cache.put(url, response.clone());
        } catch {
          // Caching is an enhancement, never a requirement.
        }
      }
      return { blobUrl: URL.createObjectURL(await response.blob()), fromCache: false };
    }
  } catch {
    // Offline or blocked; the chip shows its fallback.
  }
  return { blobUrl: null, fromCache: false };
}

export interface ChipGeometry {
  zoom: number;
  tiles: { x: number; y: number; url: string }[];
  left: number; // CSS translation of the tile grid so the point is centred
  top: number;
  size: number;
}

export function esriChip(lon: number, lat: number, zoom = 16, size = 180): ChipGeometry {
  const n = 2 ** zoom;
  const x = n * ((lon + 180) / 360);
  const merc = Math.log(Math.tan((lat + 90) * Math.PI / 360));
  const y = n * (1 - merc / Math.PI) / 2;
  const max = n - 1;
  const tx = Math.min(max, Math.max(0, Math.floor(x)));
  const ty = Math.min(max, Math.max(0, Math.floor(y)));
  const tiles = [] as { x: number; y: number; url: string }[];
  for (const dx of [0, 1]) {
    for (const dy of [0, 1]) {
      const gx = tx + dx, gy = ty + dy;
      if (gx < 0 || gx > max || gy < 0 || gy > max) continue;
      tiles.push({
        x: gx, y: gy,
        url: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${zoom}/${gy}/${gx}`,
      });
    }
  }
  const left = size / 2 - (x - tx) * size;
  const top = size / 2 - (y - ty) * size;
  return { zoom, tiles, left, top, size };
}
