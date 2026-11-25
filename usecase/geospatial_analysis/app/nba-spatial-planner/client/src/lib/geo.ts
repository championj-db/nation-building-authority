/**
 * Map geometry. Coordinates are projected with an equirectangular projection centred on the
 * scope, x scaled by cos(reference latitude), into kilometres - so a threshold of T km is drawn
 * with a radius of T map units (vertically; horizontally corrected for latitude).
 */
export type Coord = [number, number];
export type Ring = Coord[];
export interface BBox {
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
}

const KM_PER_DEG = 111.32;

export interface Projection {
  refLat: number;
  refLon: number;
  cosRef: number;
  project(lon: number, lat: number): Coord;
  unproject(x: number, y: number): Coord;
  /** Horizontal radius in map units for a true distance of `km` at latitude `lat`. */
  rx(km: number, lat: number): number;
}

export function makeProjection(bbox: BBox): Projection {
  const refLat = (bbox.ymin + bbox.ymax) / 2;
  const refLon = (bbox.xmin + bbox.xmax) / 2;
  const cosRef = Math.cos((refLat * Math.PI) / 180);
  return {
    refLat,
    refLon,
    cosRef,
    project: (lon, lat) => [(lon - refLon) * cosRef * KM_PER_DEG, -(lat - refLat) * KM_PER_DEG],
    unproject: (x, y) => [x / (cosRef * KM_PER_DEG) + refLon, refLat - y / KM_PER_DEG],
    rx: (distance, lat) => (distance * cosRef) / Math.cos((lat * Math.PI) / 180),
  };
}

/**
 * Geometry columns are JSON strings, but AppKit's transport may parse JSON-shaped strings on the
 * way through, so a value can arrive as text or as the parsed array. Accept both.
 */
function parse(json: unknown): unknown {
  if (json == null || json === '') return null;
  if (typeof json !== 'string') return json;
  try {
    return JSON.parse(json) as unknown;
  } catch {
    return null;
  }
}

const isCoord = (v: unknown): v is Coord =>
  Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';
const isRing = (v: unknown): v is Ring => Array.isArray(v) && v.length > 2 && v.every(isCoord);

/** A list of rings ([[[lon, lat], ...], ...]) as one SVG path, to be filled even-odd. */
export function ringsPath(json: unknown, projection: Projection): string {
  const rings = parse(json);
  if (!Array.isArray(rings)) return '';
  return rings
    .filter(isRing)
    .map((ring) => ringPath(ring, projection))
    .join('');
}

/** A single ring ([[lon, lat], ...]) as a closed SVG path. */
export function singleRingPath(json: unknown, projection: Projection): string {
  const ring = parse(json);
  return isRing(ring) ? ringPath(ring, projection) : '';
}

function ringPath(ring: Ring, projection: Projection) {
  let d = '';
  let lastX = NaN;
  let lastY = NaN;
  for (let i = 0; i < ring.length; i += 1) {
    const [lon, lat] = ring[i];
    const [x, y] = projection.project(lon, lat);
    const rx = Math.round(x * 10) / 10;
    const ry = Math.round(y * 10) / 10;
    if (rx === lastX && ry === lastY) continue;
    d += `${d ? 'L' : 'M'}${rx} ${ry}`;
    lastX = rx;
    lastY = ry;
  }
  return d ? `${d}Z` : '';
}

export function unionBBox(boxes: BBox[]): BBox | null {
  if (!boxes.length) return null;
  return boxes.reduce((acc, b) => ({
    xmin: Math.min(acc.xmin, b.xmin),
    xmax: Math.max(acc.xmax, b.xmax),
    ymin: Math.min(acc.ymin, b.ymin),
    ymax: Math.max(acc.ymax, b.ymax),
  }));
}

/** Projected bounding box as a viewBox [x, y, w, h], padded and fitted to an aspect ratio. */
export function fitViewBox(bbox: BBox, projection: Projection, aspect: number, padding = 0.06): ViewBox {
  const [x0, y0] = projection.project(bbox.xmin, bbox.ymax);
  const [x1, y1] = projection.project(bbox.xmax, bbox.ymin);
  let w = Math.max(x1 - x0, 1);
  let h = Math.max(y1 - y0, 1);
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  w *= 1 + padding * 2;
  h *= 1 + padding * 2;
  if (w / h > aspect) h = w / aspect;
  else w = h * aspect;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/**
 * Like fitViewBox, but frames the box inside the part of the canvas not covered by overlays
 * (toolbar along the top, legend on the right), given as pixel insets of a w x h canvas.
 */
export function fitViewBoxInset(
  bbox: BBox,
  projection: Projection,
  size: { w: number; h: number },
  inset: { top: number; right: number; bottom: number; left: number },
  padding = 0.06
): ViewBox {
  const innerW = Math.max(size.w - inset.left - inset.right, size.w * 0.5);
  const innerH = Math.max(size.h - inset.top - inset.bottom, size.h * 0.5);
  const inner = fitViewBox(bbox, projection, innerW / innerH, padding);
  const unitsPerPx = inner.w / innerW;
  return {
    x: inner.x - inset.left * unitsPerPx,
    y: inner.y - inset.top * unitsPerPx,
    w: size.w * unitsPerPx,
    h: size.h * unitsPerPx,
  };
}

export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Australia's mainland and Tasmania, used before any geometry has loaded. */
export const AUSTRALIA_BBOX: BBox = { xmin: 112.9, xmax: 153.7, ymin: -43.7, ymax: -10.6 };

/**
 * Initial framing per state: the populated mainland extent. Outlines alone would frame NSW around
 * Lord Howe Island and QLD around the Torres Strait, leaving the state off-centre and small.
 */
export const STATE_FRAMES: Record<string, BBox> = {
  NSW: { xmin: 140.9, xmax: 153.7, ymin: -37.6, ymax: -28.1 },
  VIC: { xmin: 140.9, xmax: 150.0, ymin: -39.2, ymax: -33.9 },
  QLD: { xmin: 137.9, xmax: 153.6, ymin: -29.2, ymax: -10.6 },
  SA: { xmin: 129.0, xmax: 141.0, ymin: -38.1, ymax: -25.9 },
  WA: { xmin: 112.9, xmax: 129.0, ymin: -35.2, ymax: -13.6 },
  TAS: { xmin: 143.8, xmax: 148.5, ymin: -43.7, ymax: -39.5 },
  NT: { xmin: 129.0, xmax: 138.0, ymin: -26.0, ymax: -10.9 },
  ACT: { xmin: 148.75, xmax: 149.42, ymin: -35.93, ymax: -35.12 },
};

/** Great-circle distance in km. */
export function haversineKm(a: { lon: number; lat: number }, b: { lon: number; lat: number }) {
  const toRad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * toRad;
  const dLon = (b.lon - a.lon) * toRad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * toRad) * Math.cos(b.lat * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(h)));
}
