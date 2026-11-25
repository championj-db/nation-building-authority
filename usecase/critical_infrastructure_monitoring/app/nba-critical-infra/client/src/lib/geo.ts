import { project } from './australia';

type Coord = [number, number];

/**
 * Geometry columns are stored as JSON strings, but AppKit's analytics transport parses JSON-shaped
 * strings on the way through, so a value may arrive either as text or as the parsed array (the
 * generated type still says `string`). Accept both.
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

const isCoord = (v: unknown): v is Coord => Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';
const isLine = (v: unknown): v is Coord[] => Array.isArray(v) && v.every(isCoord);

/** A single line ([[lon, lat], ...]) as an SVG path in map coordinates. */
export function linePath(json: unknown): string {
  const line = parse(json);
  return isLine(line) ? toPath(line) : '';
}

/** A multi-part line ([[[lon, lat], ...], ...]) as one SVG path. */
export function multiLinePath(json: unknown): string {
  const parts = parse(json);
  if (!Array.isArray(parts)) return '';
  return parts.filter(isLine).map(toPath).join('');
}

/** [lon, lat] points of a single line, for framing. */
export function linePoints(json: unknown): Coord[] {
  const line = parse(json);
  return isLine(line) ? line : [];
}

function toPath(line: Coord[]): string {
  if (line.length < 2) return '';
  return line
    .map(([lon, lat], i) => {
      const [x, y] = project(lon, lat);
      return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join('');
}
