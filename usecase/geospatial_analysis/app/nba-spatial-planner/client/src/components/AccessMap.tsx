import {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { ChevronDown, Minus, Plus, Search } from 'lucide-react';
import type { Analysis } from '../lib/analysis';
import { km, people, pct } from '../lib/format';
import {
  AUSTRALIA_BBOX,
  STATE_FRAMES,
  fitViewBoxInset,
  makeProjection,
  ringsPath,
  singleRingPath,
  unionBBox,
  type BBox,
  type Projection,
  type ViewBox,
} from '../lib/geo';
import { ACCESS_CLASS_LABEL, priorities, type AccessClass, type RegionAccess, type RegionShape } from '../lib/model';
import {
  GEO_LEVEL_LABELS,
  GEO_LEVEL_NOUN,
  SCOPE_LABELS,
  hexResolution,
  type AnalysisSettings,
  type ProposedSite,
} from '../lib/settings';

const FILL: Record<AccessClass, string> = {
  beyond: 'var(--class-beyond)',
  near: 'var(--class-near)',
  within: 'var(--class-within)',
  suppressed: 'url(#hatch)',
  no_population: 'var(--class-none)',
};

interface Props {
  analysis: Analysis;
  settings: AnalysisSettings;
  serviceLabel: string;
  selected: string | null;
  focusToken: number;
  placing: boolean;
  onSelect: (code: string | null) => void;
  onAddSite: (site: ProposedSite) => void;
  onLayer: (layer: AnalysisSettings['layer']) => void;
  onTogglePlacing: () => void;
  onHexRes: (res: number) => void;
  resetToken: number;
}

type Hover =
  | { kind: 'region'; code: string; x: number; y: number }
  | { kind: 'hex'; id: string; x: number; y: number }
  | { kind: 'site'; id: string; x: number; y: number }
  | null;

export function AccessMap(props: Props) {
  const { analysis, settings, serviceLabel, selected, placing, onSelect, onAddSite, onLayer, onTogglePlacing } = props;
  const { shapes, outlines, access, hex, sites, minCount } = analysis;
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 760, h: 620 });
  const [hover, setHover] = useState<Hover>(null);
  const [showRings, setShowRings] = useState(true);
  const titleId = useId();

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ w: Math.max(entry.contentRect.width, 200), h: Math.max(entry.contentRect.height, 200) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Frame: the scope's state outline, or the whole country.
  const scopeBox: BBox = useMemo(() => {
    if (settings.scope === 'AUS') return AUSTRALIA_BBOX;
    const frame = STATE_FRAMES[settings.scope];
    if (frame) return frame;
    const outline = outlines.rows.find((o) => o.state_abbr === settings.scope);
    return outline ?? unionBBox(shapes.rows) ?? AUSTRALIA_BBOX;
  }, [settings.scope, outlines.rows, shapes.rows]);
  const projection = useMemo(() => makeProjection(scopeBox), [scopeBox]);
  const [legendOpen, setLegendOpen] = useState(() => window.innerWidth > 1280);
  // Frame the scope in the canvas left free by the toolbar and the legend, so the populous
  // south-east of each state is never underneath an overlay. Fixed at mount: collapsing the
  // legend must not reset the officer's zoom.
  const [legendInset] = useState(() => (window.innerWidth > 1280 ? 224 : 0));
  const wide = size.w > 560;
  const inset = useMemo(
    () => ({ top: wide ? 100 : 120, right: wide ? legendInset : 0, bottom: 8, left: 0 }),
    [wide, legendInset]
  );
  const home = useMemo(() => fitViewBoxInset(scopeBox, projection, size, inset), [scopeBox, projection, size, inset]);
  const [view, setView] = useState<ViewBox>(home);
  useEffect(() => setView(home), [home, props.resetToken]);

  // Zoom to a region when the selection is driven from outside the map (table, search, cards).
  const shapeByCode = useMemo(() => new Map(shapes.rows.map((s) => [s.region_code, s])), [shapes.rows]);
  useEffect(() => {
    if (!props.focusToken || !selected) return;
    const shape = shapeByCode.get(selected);
    if (shape) setView(fitViewBoxInset(shape, projection, size, inset, 0.35));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.focusToken]);

  const accessByCode = useMemo(() => new Map(access.rows.map((r) => [r.region_code, r])), [access.rows]);
  const unitsPerPx = view.w / size.w;

  // Map units are km, so the view width picks the hexagon resolution (debounced while zooming).
  const { onHexRes } = props;
  useEffect(() => {
    const t = window.setTimeout(() => onHexRes(hexResolution(settings.scope, view.w)), 350);
    return () => window.clearTimeout(t);
  }, [view.w, settings.scope, onHexRes]);

  /* Pan and zoom ---------------------------------------------------------------------------- */
  const toMap = useCallback(
    (clientX: number, clientY: number): [number, number] => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return [0, 0];
      return [
        view.x + ((clientX - rect.left) / rect.width) * view.w,
        view.y + ((clientY - rect.top) / rect.height) * view.h,
      ];
    },
    [view]
  );
  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setView((v) => {
      const w = Math.min(Math.max(v.w * factor, 8), 9000);
      const h = (w / v.w) * v.h;
      return { x: cx - ((cx - v.x) / v.w) * w, y: cy - ((cy - v.y) / v.h) * h, w, h };
    });
  }, []);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      setView((v) => {
        const cx = v.x + ((event.clientX - rect.left) / rect.width) * v.w;
        const cy = v.y + ((event.clientY - rect.top) / rect.height) * v.h;
        const factor = Math.exp(event.deltaY * 0.0015);
        const w = Math.min(Math.max(v.w * factor, 8), 9000);
        const h = (w / v.w) * v.h;
        return { x: cx - ((cx - v.x) / v.w) * w, y: cy - ((cy - v.y) / v.h) * h, w, h };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean; region: string | null } | null>(
    null
  );
  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    // Pointer capture retargets later events to the svg, so remember what was pressed now.
    const region = (event.target as Element).getAttribute('data-region');
    drag.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false, region };
    (event.currentTarget as Element).setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (d) {
      const dx = event.clientX - d.x;
      const dy = event.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
      if (d.moved) {
        setHover(null);
        setView((v) => ({ ...v, x: d.vx - dx * unitsPerPx, y: d.vy - dy * unitsPerPx }));
        return;
      }
    }
    const target = event.target as Element;
    const rect = wrapRef.current?.getBoundingClientRect();
    const x = event.clientX - (rect?.left ?? 0);
    const y = event.clientY - (rect?.top ?? 0);
    const code = target.getAttribute('data-region');
    const hexId = target.getAttribute('data-hex');
    const siteId = target.getAttribute('data-site');
    if (siteId) setHover({ kind: 'site', id: siteId, x, y });
    else if (hexId) setHover({ kind: 'hex', id: hexId, x, y });
    else if (code) setHover({ kind: 'region', code, x, y });
    else setHover(null);
  };
  const onPointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) return;
    if (placing) {
      const [mx, my] = toMap(event.clientX, event.clientY);
      const [lon, lat] = projection.unproject(mx, my);
      onAddSite({ lon: Math.round(lon * 10000) / 10000, lat: Math.round(lat * 10000) / 10000 });
      return;
    }
    const code = d?.region ?? null;
    onSelect(code && code !== selected ? code : null);
  };

  /* Layers ---------------------------------------------------------------------------------- */
  const regionPaths = useMemo(
    () => shapes.rows.map((s) => ({ code: s.region_code, d: ringsPath(s.geom, projection) })),
    [shapes.rows, projection]
  );
  const statePaths = useMemo(
    () => outlines.rows.map((o) => ({ code: o.state_abbr, d: ringsPath(o.geom, projection) })),
    [outlines.rows, projection]
  );
  const hexPaths = useMemo(() => {
    const max = Math.max(1, ...hex.rows.map((h) => h.persons));
    return hex.rows.map((h) => ({
      id: h.hex_id,
      d: singleRingPath(h.ring, projection),
      cls: h.access_class,
      opacity: 0.3 + 0.7 * (Math.log1p(h.persons) / Math.log1p(max)),
    }));
  }, [hex.rows, projection]);
  const hexById = useMemo(() => new Map(hex.rows.map((h) => [h.hex_id, h])), [hex.rows]);
  const siteById = useMemo(() => new Map(sites.rows.map((s) => [s.site_id, s])), [sites.rows]);
  const selectedPath = selected ? regionPaths.find((p) => p.code === selected)?.d : undefined;

  const labelled = useMemo(() => priorities(access.rows, 6), [access.rows]);
  const loading = shapes.loading || access.loading || (hex.enabled && hex.loading);
  const refreshing = shapes.refreshing || access.refreshing || hex.refreshing;
  const error = shapes.error ?? access.error ?? (hex.enabled ? hex.error : null);

  const regionCount = access.rows.length;
  const meta =
    settings.layer === 'hexagons'
      ? `H3 res ${hex.res} hexagons · zoom for finer cells · ${minCount ? `under ${minCount} residents hidden` : 'unsuppressed'}`
      : access.loading
        ? `${GEO_LEVEL_LABELS[settings.geoLevel]} · loading`
        : `${GEO_LEVEL_LABELS[settings.geoLevel]} · ${regionCount} ${GEO_LEVEL_NOUN[settings.geoLevel]} · aggregate view`;
  const noSites = !sites.loading && !sites.error && sites.data != null && sites.rows.length === 0;

  const description = `${SCOPE_LABELS[settings.scope]}: ${regionCount} ${GEO_LEVEL_NOUN[settings.geoLevel]} coloured by modelled straight-line distance to the nearest ${serviceLabel.toLowerCase()}, against a ${settings.threshold} km threshold. ${
    access.rows.filter((r) => r.access_class === 'beyond').length
  } beyond, ${access.rows.filter((r) => r.access_class === 'near').length} near. The evidence queue below lists the same regions as a table.`;

  return (
    <div className="map" ref={wrapRef}>
      <svg
        ref={svgRef}
        className={placing ? 'placing' : undefined}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-labelledby={titleId}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHover(null)}
      >
        <title id={titleId}>{description}</title>
        <defs>
          <pattern
            id="hatch"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform={`rotate(45) scale(${unitsPerPx})`}
          >
            <rect width="6" height="6" fill="var(--bg)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--line)" strokeWidth="3" />
          </pattern>
        </defs>
        <rect x={view.x - view.w} y={view.y - view.h} width={view.w * 3} height={view.h * 3} fill="var(--bg)" />

        <StateLayer paths={statePaths} />

        {settings.layer === 'regions' ? (
          <RegionLayer paths={regionPaths} accessByCode={accessByCode} boundaries={settings.boundaries} />
        ) : (
          <>
            <HexLayer paths={hexPaths} />
            {settings.boundaries && <OutlineLayer paths={regionPaths} />}
          </>
        )}

        {settings.boundaries && (
          <g
            fill="none"
            stroke="var(--fg-muted)"
            strokeWidth={1.25}
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          >
            {statePaths.map((p) => (
              <path key={p.code} d={p.d} vectorEffect="non-scaling-stroke" />
            ))}
          </g>
        )}

        {selectedPath && (
          <path
            d={selectedPath}
            fill="none"
            stroke="var(--fg)"
            strokeWidth={3}
            vectorEffect="non-scaling-stroke"
            fillRule="evenodd"
            pointerEvents="none"
          />
        )}

        <SiteLayer
          sites={sites.rows}
          projection={projection}
          unitsPerPx={unitsPerPx}
          threshold={settings.threshold}
          rings={showRings && sites.rows.length <= 1500}
        />

        <g pointerEvents="none">
          {settings.sites.map((s, i) => {
            const [x, y] = projection.project(s.lon, s.lat);
            return (
              <g key={`${s.lon},${s.lat}`}>
                <ellipse
                  cx={x}
                  cy={y}
                  rx={projection.rx(settings.threshold, s.lat)}
                  ry={settings.threshold}
                  fill="color-mix(in oklab, var(--lava), transparent 88%)"
                  stroke="var(--lava)"
                  strokeWidth={2}
                  strokeDasharray="6 5"
                  vectorEffect="non-scaling-stroke"
                />
                <circle
                  cx={x}
                  cy={y}
                  r={7 * unitsPerPx}
                  fill="var(--lava)"
                  stroke="var(--surface)"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={x}
                  y={y + 3.6 * unitsPerPx}
                  textAnchor="middle"
                  fontSize={9 * unitsPerPx}
                  fontWeight={700}
                  fill="var(--lava-on)"
                >
                  {i + 1}
                </text>
              </g>
            );
          })}
        </g>

        {settings.layer === 'regions' && (
          <g className="map-label" textAnchor="middle" fontSize={12 * unitsPerPx} strokeWidth={4 * unitsPerPx}>
            {placeLabels(labelled, shapeByCode, projection, unitsPerPx).map((l) => (
              <text key={l.code} x={l.x} y={l.y}>
                {l.text}
              </text>
            ))}
          </g>
        )}
      </svg>

      <div className="map-toolbar">
        <RegionSearch shapes={shapes.rows} onPick={(code) => onSelect(code)} />
        <div className="row" style={{ gap: 8, alignItems: 'start' }}>
          <div className="segmented" role="group" aria-label="Map layer">
            <button type="button" aria-pressed={settings.layer === 'regions'} onClick={() => onLayer('regions')}>
              Regions
            </button>
            <button type="button" aria-pressed={settings.layer === 'hexagons'} onClick={() => onLayer('hexagons')}>
              H3 grid
            </button>
          </div>
          <div className="segmented" role="group" aria-label="Map tools">
            <button
              type="button"
              aria-pressed={showRings}
              onClick={() => setShowRings((v) => !v)}
              title="Show the access threshold around each site"
            >
              Radius
            </button>
            <button
              type="button"
              aria-pressed={placing}
              onClick={onTogglePlacing}
              title="Click the map to propose a new site"
            >
              {placing ? 'Placing…' : 'Add site'}
            </button>
          </div>
          <div className="zoom-stack">
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => zoomAt(0.6, view.x + view.w / 2, view.y + view.h / 2)}
            >
              <Plus className="icon" aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => zoomAt(1.6, view.x + view.w / 2, view.y + view.h / 2)}
            >
              <Minus className="icon" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
      {placing ? (
        <div className="placing-hint">Click the map to place a proposed site · Esc to stop</div>
      ) : (
        noSites && (
          <div className="placing-hint quiet" role="note">
            No {serviceLabel.toLowerCase()} in {SCOPE_LABELS[settings.scope]}. Distances run to the nearest site
            elsewhere.
          </div>
        )
      )}

      {hover && (
        <Tooltip
          hover={hover}
          access={accessByCode}
          hexById={hexById}
          siteById={siteById}
          shapes={shapeByCode}
          minCount={minCount}
          threshold={settings.threshold}
        />
      )}

      <div className="map-meta">{meta}</div>
      <details
        className="legend"
        open={legendOpen}
        onToggle={(e) => setLegendOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary>
          <strong>Modelled nearest-service distance</strong>
          <ChevronDown className="icon legend-chevron" aria-hidden="true" />
        </summary>
        <div>
          <span className="swatch" aria-hidden="true" />
          Within threshold
        </div>
        <div>
          <span className="swatch near" aria-hidden="true" />
          Near threshold (75–100%)
        </div>
        <div>
          <span className="swatch beyond" aria-hidden="true" />
          Beyond threshold
        </div>
        {minCount > 0 && settings.layer === 'regions' && (
          <div>
            <span className="swatch suppressed" aria-hidden="true" />
            Suppressed (under {minCount})
          </div>
        )}
        <div>
          <span className="swatch site" aria-hidden="true" />
          {serviceLabel}
        </div>
        {settings.sites.length > 0 && (
          <div>
            <span className="swatch proposed" aria-hidden="true" />
            Proposed site
          </div>
        )}
        <div className="muted" style={{ marginTop: 8 }}>
          {settings.layer === 'hexagons' ? 'Stronger colour = more residents. ' : ''}Class uses the median resident.
        </div>
      </details>

      {(loading || refreshing || error) && (
        <div className="map-overlay">
          {error ? (
            <div role="alert">Map data did not load. {error}</div>
          ) : loading ? (
            <div>
              <span className="spinner" aria-hidden="true" />
              Loading boundaries and access results…
            </div>
          ) : (
            <div>
              <span className="spinner" aria-hidden="true" />
              Updating…
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Greedy label placement in priority order: a label is dropped if its box (estimated from the
 * text length at 12 px) would overlap one already placed, so the most important names win.
 */
function placeLabels(
  rows: RegionAccess[],
  shapes: Map<string, RegionShape>,
  projection: Projection,
  unitsPerPx: number
) {
  const placed: { code: string; text: string; x: number; y: number; box: [number, number, number, number] }[] = [];
  for (const r of rows) {
    const shape = shapes.get(r.region_code);
    if (!shape) continue;
    const text = shortName(r.region_name);
    const [x, y] = projection.project(shape.label_lon, shape.label_lat);
    const halfW = (text.length * 6.6 * unitsPerPx) / 2 + 4 * unitsPerPx;
    const box: [number, number, number, number] = [x - halfW, y - 13 * unitsPerPx, x + halfW, y + 4 * unitsPerPx];
    const clash = placed.some((p) => box[0] < p.box[2] && box[2] > p.box[0] && box[1] < p.box[3] && box[3] > p.box[1]);
    if (!clash) placed.push({ code: r.region_code, text, x, y, box });
  }
  return placed;
}

function shortName(name: string) {
  return name.replace(/ - /g, ' – ').replace(/\s*\((NSW|VIC|QLD|SA|WA|TAS|NT|ACT|OT)\)$/, '');
}

/* Memoised layers: hover, selection and zoom do not re-render thousands of paths. ------------ */

const StateLayer = memo(function StateLayer({ paths }: { paths: { code: string; d: string }[] }) {
  return (
    <g fill="var(--surface)" stroke="none" pointerEvents="none">
      {paths.map((p) => (
        <path key={p.code} d={p.d} fillRule="evenodd" />
      ))}
    </g>
  );
});

const RegionLayer = memo(function RegionLayer({
  paths,
  accessByCode,
  boundaries,
}: {
  paths: { code: string; d: string }[];
  accessByCode: Map<string, RegionAccess>;
  boundaries: boolean;
}) {
  return (
    <g stroke={boundaries ? 'var(--surface)' : 'none'} strokeWidth={0.8} strokeLinejoin="round">
      {paths.map((p) => {
        const cls = accessByCode.get(p.code)?.access_class ?? 'no_population';
        return (
          <path
            key={p.code}
            className="region-path"
            d={p.d}
            data-region={p.code}
            fill={FILL[cls]}
            fillRule="evenodd"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </g>
  );
});

const OutlineLayer = memo(function OutlineLayer({ paths }: { paths: { code: string; d: string }[] }) {
  return (
    <g fill="transparent" stroke="var(--fg)" strokeOpacity={0.35} strokeWidth={0.8}>
      {paths.map((p) => (
        <path key={p.code} d={p.d} data-region={p.code} fillRule="evenodd" vectorEffect="non-scaling-stroke" />
      ))}
    </g>
  );
});

const HexLayer = memo(function HexLayer({
  paths,
}: {
  paths: { id: string; d: string; cls: AccessClass; opacity: number }[];
}) {
  return (
    <g stroke="var(--surface)" strokeWidth={0.4}>
      {paths.map((p) => (
        <path
          key={p.id}
          d={p.d}
          data-hex={p.id}
          fill={FILL[p.cls]}
          fillOpacity={p.opacity}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </g>
  );
});

function SiteLayer({
  sites,
  projection,
  unitsPerPx,
  threshold,
  rings,
}: {
  sites: Analysis['sites']['rows'];
  projection: Projection;
  unitsPerPx: number;
  threshold: number;
  rings: boolean;
}) {
  const projected = useMemo(
    () => sites.map((s) => ({ id: s.site_id, lat: s.latitude, xy: projection.project(s.longitude, s.latitude) })),
    [sites, projection]
  );
  const r = Math.max(2.5, Math.min(6, 4.5)) * unitsPerPx;
  return (
    <>
      {rings && (
        <g fill="none" stroke="var(--surface)" strokeWidth={1.25} opacity={0.85} pointerEvents="none">
          {projected.map((s) => (
            <ellipse
              key={s.id}
              cx={s.xy[0]}
              cy={s.xy[1]}
              rx={projection.rx(threshold, s.lat)}
              ry={threshold}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>
      )}
      <g fill="var(--surface)" stroke="var(--fg)" strokeWidth={2} vectorEffect="non-scaling-stroke">
        {projected.map((s) => (
          <circle key={s.id} cx={s.xy[0]} cy={s.xy[1]} r={r} data-site={s.id} vectorEffect="non-scaling-stroke" />
        ))}
      </g>
    </>
  );
}

/* Tooltip ------------------------------------------------------------------------------------ */

function Tooltip({
  hover,
  access,
  hexById,
  siteById,
  shapes,
  minCount,
  threshold,
}: {
  hover: NonNullable<Hover>;
  access: Map<string, RegionAccess>;
  hexById: Map<string, Analysis['hex']['rows'][number]>;
  siteById: Map<string, Analysis['sites']['rows'][number]>;
  shapes: Map<string, RegionShape>;
  minCount: number;
  threshold: number;
}) {
  const style = { left: Math.min(hover.x + 16, window.innerWidth), top: hover.y + 16 };
  if (hover.kind === 'site') {
    const site = siteById.get(hover.id);
    if (!site) return null;
    return (
      <div className="map-tooltip" style={style}>
        <strong>{site.name}</strong>
        <div className="muted xs" style={{ marginBottom: 6 }}>
          {[site.suburb, site.state_abbr].filter(Boolean).join(', ')}
        </div>
        <dl className="kv">
          <dt>Nearest for</dt>
          <dd>{people(site.catchment_persons, minCount)} people</dd>
          <dt>Median catchment distance</dt>
          <dd>{km(site.catchment_median_km)}</dd>
          {site.capacity_places != null && (
            <>
              <dt>Residential places</dt>
              <dd>{site.capacity_places}</dd>
            </>
          )}
        </dl>
      </div>
    );
  }
  if (hover.kind === 'hex') {
    const cell = hexById.get(hover.id);
    if (!cell) return null;
    return (
      <div className="map-tooltip" style={style}>
        <strong>H3 cell {cell.hex_id.slice(0, 8)}…</strong>
        <dl className="kv">
          <dt>Residents</dt>
          <dd>{people(cell.persons, minCount)}</dd>
          <dt>Beyond {threshold} km</dt>
          <dd>{people(cell.persons_beyond, minCount)}</dd>
          <dt>Median distance</dt>
          <dd>{km(cell.median_km)}</dd>
          <dt>Class</dt>
          <dd>{ACCESS_CLASS_LABEL[cell.access_class]}</dd>
        </dl>
      </div>
    );
  }
  const row = access.get(hover.code);
  const shape = shapes.get(hover.code);
  if (!row && !shape) return null;
  return (
    <div className="map-tooltip" style={style}>
      <strong>{row?.region_name ?? shape?.region_name}</strong>
      {row ? (
        <dl className="kv">
          <dt>Residents</dt>
          <dd>{people(row.persons, minCount)}</dd>
          <dt>Beyond {threshold} km</dt>
          <dd>
            {people(row.persons_beyond, minCount, row.persons_beyond == null)} ({pct(row.share_beyond)})
          </dd>
          <dt>Median distance</dt>
          <dd>{km(row.median_km)}</dd>
          <dt>Class</dt>
          <dd>{ACCESS_CLASS_LABEL[row.access_class]}</dd>
        </dl>
      ) : (
        <div className="muted xs">No residents</div>
      )}
    </div>
  );
}

/* Region search (keyboard-accessible combobox) ---------------------------------------------- */

function RegionSearch({ shapes, onPick }: { shapes: RegionShape[]; onPick: (code: string) => void }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return shapes.filter((s) => s.region_name.toLowerCase().includes(q)).slice(0, 8);
  }, [query, shapes]);
  const pick = (code: string) => {
    onPick(code);
    setQuery('');
    setOpen(false);
  };
  return (
    <div className="search">
      <Search className="icon search-icon" aria-hidden="true" />
      <input
        type="search"
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label="Find a region"
        placeholder="Find a region"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, matches.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter' && matches[active]) {
            e.preventDefault();
            pick(matches[active].region_code);
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
      />
      {open && matches.length > 0 && (
        <ul className="search-results" id={listId} role="listbox">
          {matches.map((m, i) => (
            <li key={m.region_code} role="option" aria-selected={i === active}>
              <button
                type="button"
                tabIndex={-1}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(m.region_code)}
              >
                <span>{m.region_name}</span>
                <span className="muted xs">{m.state_abbr}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
