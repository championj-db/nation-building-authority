import { useMemo, useRef, useState } from 'react';
import { KM, MAP_WIDTH, STATES, project } from '../lib/australia';
import { formatHours, formatInt, formatPeople } from '../lib/format';
import { linePath, linePoints, multiLinePath } from '../lib/geo';
import { HAZARD_LABELS, SECTORS, SECTOR_LABELS, STATUS_LABELS, type Sector } from '../lib/model';
import { isTrue, type DisruptionRow, type HazardRouteRow, type HazardRow, type ImpactRow, type IncidentRow, type NetworkAssetRow, type RailRow, type RiverRow, type RoadRow } from '../lib/rows';
import { HazardIcon, SectorBadge, SectorIcon } from './icons';
import { EmptyState, ErrorState, Skeleton } from './primitives';

/** Region focus boxes: [west lon, north lat, east lon, south lat]. */
const REGIONS: { id: string; label: string; box: [number, number, number, number] }[] = [
  { id: 'national', label: 'National', box: [112.5, -9.5, 154.2, -44.0] },
  { id: 'nsw', label: 'NSW & ACT', box: [140.6, -27.6, 154.0, -37.8] },
  { id: 'vic', label: 'VIC & TAS', box: [140.6, -33.8, 150.6, -43.8] },
  { id: 'qld', label: 'QLD', box: [137.8, -10.0, 154.2, -29.4] },
  { id: 'sa', label: 'SA', box: [128.8, -25.8, 141.2, -38.3] },
  { id: 'wa', label: 'WA', box: [112.6, -13.4, 129.2, -35.4] },
  { id: 'nt', label: 'NT', box: [128.8, -10.8, 138.2, -26.2] },
];

function viewBoxFor([w, n, e, s]: [number, number, number, number]) {
  const [x0, y0] = project(w, n);
  const [x1, y1] = project(e, s);
  const pad = (x1 - x0) * 0.03;
  return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad };
}

const RATING_R: Record<string, number> = { extreme: 7.5, high: 6, medium: 4.8 };

interface Props {
  assets: NetworkAssetRow[] | null;
  hazards: HazardRow[] | null;
  incidents: IncidentRow[] | null;
  impacts: Map<string, ImpactRow[]>;
  roads: RoadRow[] | null;
  rail: RailRow[] | null;
  rivers: RiverRow[] | null;
  disruptions: Map<string, DisruptionRow>;
  hazardRoutes: Map<string, HazardRouteRow[]>;
  loading: boolean;
  error: string | null;
  onReview: (incident: IncidentRow) => void;
}

export function NetworkMap({ assets, hazards, incidents, impacts, roads, rail, rivers, disruptions, hazardRoutes, loading, error, onReview }: Props) {
  const [region, setRegion] = useState('national');
  const [hazardFocus, setHazardFocus] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<Sector>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // selecting an incident frames it and its dependants; a region or warning click takes over again
  const [frameSelection, setFrameSelection] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; title: string; sub: string } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const selected = incidents?.find((i) => i.incident_id === selectedId) ?? null;
  const cascade = useMemo(() => (selected ? (impacts.get(String(selected.incident_id)) ?? []) : []), [selected, impacts]);
  const disruption = selected ? (disruptions.get(String(selected.incident_id)) ?? null) : null;

  // network geometry is large: project it once per data load, not per render
  const roadPaths = useMemo(() => (roads ?? []).map((r) => ({ id: String(r.segment_id), name: r.name, d: multiLinePath(r.display_coords) })), [roads]);
  const railPaths = useMemo(() => (rail ?? []).map((r) => ({ id: String(r.segment_id), d: multiLinePath(r.display_coords) })), [rail]);
  const riverPaths = useMemo(() => (rivers ?? []).map((r) => ({ id: String(r.river_id), name: r.name, intermittent: isTrue(r.intermittent), d: multiLinePath(r.display_coords) })), [rivers]);
  const sectionPath = useMemo(() => linePath(disruption?.section_coords), [disruption]);
  const detourPath = useMemo(() => linePath(disruption?.detour_coords), [disruption]);
  // every open road or rail incident's affected section, always visible (not only when selected)
  const openIds = useMemo(() => new Set((incidents ?? []).filter((i) => i.status === 'open').map((i) => String(i.incident_id))), [incidents]);
  const allSections = useMemo(
    () =>
      [...disruptions.values()]
        .filter((d) => openIds.has(String(d.incident_id)))
        .map((d) => ({ d, path: linePath(d.section_coords) }))
        .filter((x) => x.path),
    [disruptions, openIds],
  );

  const vb = useMemo(() => {
    if (frameSelection && selected) {
      // frame the incident and what it supplies directly; second-hop links may run off-frame
      const direct = cascade.filter((c) => Number(c.hop) === 1);
      // a network incident also frames its closed section and the detour around it
      const networkPts = [...linePoints(disruption?.section_coords), ...linePoints(disruption?.detour_coords)].map(([lon, lat]) => project(lon, lat));
      const pts = [...[selected, ...direct].map((p) => project(Number(p.longitude), Number(p.latitude))), ...networkPts];
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      // at least ~0.7 degrees across (so assets a few km apart separate), padded, near the map's aspect
      let w = Math.max(18, (Math.max(...xs) - Math.min(...xs)) * 1.6);
      let h = Math.max(14, (Math.max(...ys) - Math.min(...ys)) * 1.6);
      if (w / h < 1.3) w = h * 1.3;
      else h = w / 1.3;
      return { x: cx - w / 2, y: cy - h / 2, w, h };
    }
    const h = hazards?.find((x) => x.warning_id === hazardFocus);
    if (h) {
      const lat = Number(h.centre_lat), lon = Number(h.centre_lon), r = Number(h.radius_km) * 1.6;
      const dLat = r / 111.32, dLon = r / (111.32 * Math.cos((lat * Math.PI) / 180));
      return viewBoxFor([lon - dLon * 1.3, lat + dLat, lon + dLon * 1.3, lat - dLat]);
    }
    return viewBoxFor(REGIONS.find((r) => r.id === region)?.box ?? REGIONS[0].box);
  }, [region, hazardFocus, hazards, frameSelection, selected, cascade, disruption]);
  const zoom = vb.w / MAP_WIDTH; // marker sizes stay constant on screen

  const visibleIncidents = (incidents ?? []).filter((i) => !hidden.has(i.sector as Sector) && i.status === 'open');
  const decidedIncidents = (incidents ?? []).filter((i) => !hidden.has(i.sector as Sector) && i.status !== 'open');

  const toggle = (sector: Sector) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(sector)) next.delete(sector);
      else next.add(sector);
      return next;
    });

  const showTip = (evt: React.MouseEvent, title: string, sub: string) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (rect) setHover({ x: evt.clientX - rect.left, y: evt.clientY - rect.top, title, sub });
  };

  return (
    <section className="section" id="map" aria-labelledby="map-heading">
      <div className="container">
        <div className="row-between section-heading">
          <div>
            <p className="eyebrow">Network map</p>
            <h2 id="map-heading">Where the risk is, and what depends on it</h2>
            <p className="lead">Select an incident to see the assets that rely on it. Warning areas come from the weather warnings feed.</p>
          </div>
        </div>

        <div className="map-layout">
          <div className="card map-card">
            <div className="map-toolbar">
              <div className="segmented" role="group" aria-label="Map region">
                {REGIONS.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    className={region === r.id && !hazardFocus && !frameSelection ? 'on' : ''}
                    aria-pressed={region === r.id && !hazardFocus && !frameSelection}
                    onClick={() => {
                      setHazardFocus(null);
                      setFrameSelection(false);
                      setRegion(r.id);
                    }}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <div className="sector-toggles" role="group" aria-label="Show sectors">
                {SECTORS.map((s) => (
                  <button key={s} type="button" className={`chip sector-${s}${hidden.has(s) ? ' off' : ''}`} aria-pressed={!hidden.has(s)} onClick={() => toggle(s)}>
                    <SectorIcon sector={s} size={13} />
                    {SECTOR_LABELS[s]}
                  </button>
                ))}
              </div>
            </div>

            <div className="map-wrap" ref={wrapRef} onMouseLeave={() => setHover(null)}>
              {error && !assets ? (
                <div style={{ padding: 20 }}>
                  <ErrorState title="The network map could not load" message={error} />
                </div>
              ) : loading && !assets ? (
                <Skeleton height={520} />
              ) : !assets?.length ? (
                <EmptyState title="No assets to show">Run the pipeline job to build the asset registry.</EmptyState>
              ) : (
                <svg
                  className="network-map"
                  viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
                  role="group"
                  aria-label={`Map of ${formatInt(assets.length)} monitored assets, ${visibleIncidents.length} open incidents and ${hazards?.length ?? 0} active warnings`}
                  onClick={(e) => {
                    if (e.target === e.currentTarget) {
                      setSelectedId(null);
                      setFrameSelection(false);
                    }
                  }}
                >
                  {STATES.map((s) => (
                    <path key={s.code} d={s.d} className="state" style={{ strokeWidth: 1 * zoom }} />
                  ))}

                  {!hidden.has('water') ? (
                    <g className="net-rivers" aria-hidden="true">
                      {riverPaths.map((r) => (
                        <path key={r.id} d={r.d} className={r.intermittent ? 'river intermittent' : 'river'} style={{ strokeWidth: (r.intermittent ? 0.7 : 1.1) * zoom }} />
                      ))}
                    </g>
                  ) : null}

                  {(hazards ?? []).map((h) => {
                    const [cx, cy] = project(Number(h.centre_lon), Number(h.centre_lat));
                    return (
                      <g key={String(h.warning_id)} className={`hazard-area sev-${h.severity}${hazardFocus === h.warning_id ? ' focus' : ''}`}>
                        <circle cx={cx} cy={cy} r={Number(h.radius_km) * KM} style={{ strokeWidth: 1.5 * zoom, strokeDasharray: `${5 * zoom} ${4 * zoom}` }}
                          onMouseMove={(e) => showTip(e, String(h.title), `${h.severity} · ${formatInt(h.exposed_assets)} assets inside · ends in ${formatHours(h.hours_remaining)}`)} />
                      </g>
                    );
                  })}

                  {!hidden.has('roads') ? (
                    <g className="net-roads">
                      {roadPaths.map((r) => (
                        <path key={r.id} d={r.d} className="road" style={{ strokeWidth: 1.6 * zoom }}
                          onMouseMove={(e) => r.name && showTip(e, r.name, 'Key freight route (road)')} />
                      ))}
                    </g>
                  ) : null}
                  {!hidden.has('rail') ? (
                    <g className="net-rail">
                      {railPaths.map((r) => (
                        <path key={r.id} d={r.d} className="rail" style={{ strokeWidth: 1.3 * zoom, strokeDasharray: `${4 * zoom} ${2 * zoom}` }}
                          onMouseMove={(e) => showTip(e, 'Key freight route (rail)', 'Department of Infrastructure')} />
                      ))}
                    </g>
                  ) : null}

                  {allSections
                    .filter(({ d }) => !hidden.has(d.network_mode === 'rail' ? 'rail' : 'roads') && d.incident_id !== selectedId)
                    .map(({ d, path }) => {
                      const incident = incidents?.find((i) => i.incident_id === d.incident_id);
                      return (
                        <path
                          key={`sec-${d.incident_id}`}
                          d={path}
                          className={`affected-section${d.network_effect === 'restriction' ? ' restriction' : ''}`}
                          style={{ strokeWidth: 3 * zoom }}
                          onMouseMove={(e) =>
                            showTip(e, String(d.route_name), `${incident?.asset_name ?? 'Network incident'} · ${incident?.network_summary?.replace(/^[^:]+: /, '') ?? ''}`)
                          }
                          onClick={() => {
                            setSelectedId(String(d.incident_id));
                            setFrameSelection(true);
                          }}
                        />
                      );
                    })}

                  {disruption && detourPath ? (
                    <path d={detourPath} className="detour" style={{ strokeWidth: 3 * zoom, strokeDasharray: `${6 * zoom} ${4 * zoom}` }}>
                      <title>Detour{disruption.detour_via ? ` via ${disruption.detour_via}` : ''}</title>
                    </path>
                  ) : null}
                  {disruption && sectionPath ? (
                    <path d={sectionPath} className={`closed-section${disruption.network_effect === 'restriction' ? ' restriction' : ''}`} style={{ strokeWidth: 4.5 * zoom }}>
                      <title>{disruption.network_effect === 'restriction' ? 'Restricted' : 'Unusable'} between junctions: {disruption.route_name}</title>
                    </path>
                  ) : null}

                  {assets.filter((a) => !hidden.has(a.sector as Sector)).map((a) => {
                    const [x, y] = project(Number(a.longitude), Number(a.latitude));
                    return (
                      <circle key={String(a.asset_id)} cx={x} cy={y} r={2.1 * zoom} className={`asset-dot sector-${a.sector}`}
                        onMouseMove={(e) => showTip(e, String(a.asset_name), `${SECTOR_LABELS[a.sector as Sector] ?? a.sector} · risk ${a.risk_score}`)} />
                    );
                  })}

                  {cascade.map((c) => {
                    const [x0, y0] = project(Number(selected!.longitude), Number(selected!.latitude));
                    const [x1, y1] = project(Number(c.longitude), Number(c.latitude));
                    return (
                      <g key={`${c.incident_id}-${c.downstream_asset_id}`} className="cascade">
                        <line x1={x0} y1={y0} x2={x1} y2={y1} style={{ strokeWidth: (Number(c.hop) === 1 ? 2.2 : 1.1) * zoom, strokeDasharray: Number(c.hop) === 1 ? undefined : `${3 * zoom} ${3 * zoom}` }} />
                        <circle cx={x1} cy={y1} r={3.4 * zoom} className={`cascade-node sector-${c.sector}`} style={{ strokeWidth: 1.4 * zoom }}
                          onMouseMove={(e) => showTip(e, String(c.asset_name), `${c.dependency_type} · ${formatPeople(c.people_served)} people`)} />
                      </g>
                    );
                  })}

                  {[...decidedIncidents, ...visibleIncidents].map((i) => {
                    const [x, y] = project(Number(i.longitude), Number(i.latitude));
                    const isSel = i.incident_id === selectedId;
                    const decided = i.status !== 'open';
                    return (
                      <g
                        key={String(i.incident_id)}
                        className={`incident-marker rating-${i.risk_rating}${isSel ? ' selected' : ''}${decided ? ' decided' : ''}`}
                        role="button"
                        tabIndex={0}
                        aria-label={`${i.asset_name}: ${i.incident_title}, ${i.risk_rating} risk ${i.risk_score}${decided ? `, ${STATUS_LABELS[String(i.status)]}` : ''}`}
                        onClick={() => {
                          setSelectedId(isSel ? null : String(i.incident_id));
                          setFrameSelection(!isSel);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setSelectedId(isSel ? null : String(i.incident_id));
                            setFrameSelection(!isSel);
                          }
                        }}
                        onMouseMove={(e) => showTip(e, String(i.asset_name), `${i.incident_title} · ${i.risk_rating} ${i.risk_score}`)}
                      >
                        <circle cx={x} cy={y} r={(RATING_R[String(i.risk_rating)] ?? 5) * zoom * (isSel ? 1.3 : 1)} className={`sector-${i.sector}`} style={{ strokeWidth: 2.2 * zoom }} />
                      </g>
                    );
                  })}
                </svg>
              )}
              {hover ? (
                <div className="map-tip" style={{ left: hover.x + 14, top: hover.y + 10 }} role="presentation">
                  <strong>{hover.title}</strong>
                  <span>{hover.sub}</span>
                </div>
              ) : null}
            </div>

            <div className="map-legend" aria-hidden="true">
              <span><i className="lg-dot" /> Asset</span>
              <span><i className="lg-inc extreme" /> Extreme</span>
              <span><i className="lg-inc high" /> High</span>
              <span><i className="lg-inc medium" /> Medium</span>
              <span><i className="lg-hazard" /> Warning area</span>
              <span><i className="lg-road" /> Key freight road</span>
              <span><i className="lg-rail" /> Key freight rail</span>
              <span><i className="lg-river" /> River</span>
              <span><i className="lg-line" /> Supply link (selected)</span>
              <span><i className="lg-closed" /> Affected section of a road or rail incident</span>
              <span><i className="lg-detour" /> Detour (selected incident)</span>
            </div>
          </div>

          <aside className="map-side">
            {selected ? (
              <div className="card selected-card" aria-live="polite">
                <div className="row-between">
                  <SectorBadge sector={String(selected.sector)} />
                  <span className={`sev ${selected.risk_rating === 'extreme' ? 'critical' : selected.risk_rating}`}>
                    {selected.risk_rating} · {selected.risk_score}
                  </span>
                </div>
                <h3 style={{ marginTop: 10 }}>{selected.asset_name}</h3>
                <p className="alert-copy" style={{ marginTop: 0 }}>{selected.incident_title}</p>
                {selected.network_summary ? (
                  <p className="network-line">
                    <strong>{selected.network_effect === 'restriction' ? 'Restricts' : 'Closes'}</strong> {selected.network_summary}
                  </p>
                ) : null}
                <p className="meta" style={{ margin: '8px 0 12px' }}>
                  {cascade.length
                    ? `${cascade.length} dependent asset${cascade.length === 1 ? '' : 's'} · ${formatPeople(selected.people_affected)} people relying on these services`
                    : `No dependent assets · ${formatPeople(selected.people_served)} people served`}
                </p>
                {cascade.length ? (
                  <ul className="dependant-list" aria-label="Assets that depend on this one">
                    {cascade.slice(0, 5).map((c) => (
                      <li key={String(c.downstream_asset_id)}>
                        <SectorIcon sector={String(c.sector)} size={13} className={`sector-${c.sector} dep-icon`} />
                        <span>{c.asset_name}</span>
                        {Number(c.hop) === 2 ? <span className="meta">via supply</span> : null}
                      </li>
                    ))}
                    {cascade.length > 5 ? <li className="meta">+{cascade.length - 5} more in the review</li> : null}
                  </ul>
                ) : null}
                <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => onReview(selected)}>
                  Review incident
                </button>
              </div>
            ) : null}

            <div className="card hazards-card">
              <h3>Active warnings</h3>
              {!hazards ? (
                <Skeleton height={160} />
              ) : hazards.length === 0 ? (
                <EmptyState title="No active warnings" />
              ) : (
                <ul className="hazard-list">
                  {hazards.map((h) => (
                    <li key={String(h.warning_id)}>
                      <button
                        type="button"
                        className={`hazard-item${hazardFocus === h.warning_id ? ' on' : ''}`}
                        aria-pressed={hazardFocus === h.warning_id}
                        onClick={() => {
                          setFrameSelection(false);
                          setHazardFocus(hazardFocus === h.warning_id ? null : String(h.warning_id));
                        }}
                      >
                        <span className={`hazard-glyph sev-${h.severity}`}>
                          <HazardIcon type={String(h.hazard_type)} size={16} />
                        </span>
                        <span className="hazard-body">
                          <strong>{String(h.title).replace(/^[^-]+- /, '')}</strong>
                          <span className="meta">
                            {HAZARD_LABELS[String(h.hazard_type)]} · {h.severity} · ends in {formatHours(h.hours_remaining)}
                          </span>
                          <span className="hazard-exposure">
                            {SECTORS.map((s) => {
                              const n = Number(h[`exposed_${s}` as keyof HazardRow] ?? 0);
                              return n ? (
                                <span key={s} className={`exp sector-${s}`} title={`${n} ${SECTOR_LABELS[s].toLowerCase()} assets in the warning area`}>
                                  <SectorIcon sector={s} size={12} /> {n}
                                </span>
                              ) : null;
                            })}
                            {(hazardRoutes.get(String(h.warning_id)) ?? []).slice(0, 2).map((r) => (
                              <span key={`${r.mode}-${r.route_name}`} className={`exp route sector-${r.mode === 'rail' ? 'rail' : 'roads'}`} title="Key freight route inside the warning area">
                                {r.route_name} {Math.round(Number(r.km_inside))} km
                              </span>
                            ))}
                            {Number(h.linked_incidents) ? <span className="exp linked">{h.linked_incidents} incident{Number(h.linked_incidents) === 1 ? '' : 's'}</span> : null}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
        <p className="meta" style={{ marginTop: 10 }}>
          Road and rail: National Key Freight Routes, Department of Infrastructure (CC BY 4.0). Outlines and rivers: Natural Earth
          (public domain). Every asset, operator, reading and warning is synthetic.
        </p>
      </div>
    </section>
  );
}

