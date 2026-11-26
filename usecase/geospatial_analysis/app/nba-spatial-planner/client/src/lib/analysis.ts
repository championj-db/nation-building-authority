import { useMemo } from 'react';
import { arrowRows, sql, useAnalyticsQuery, useBaseParams, useRows, useScope, useSticky } from './data';
import type {
  HexCell,
  RegionAccess,
  RegionShape,
  RemotenessRow,
  ReviewNoteRow,
  ScenarioRow,
  ScopeSummary,
  ServiceSite,
  StateOutline,
} from './model';
import type { AnalysisSettings } from './settings';

/** Disclosure threshold actually in force: 0 (no suppression) when the officer turns it off. */
export function useMinCount(settings: AnalysisSettings) {
  const { minCount } = useScope();
  return settings.suppress ? minCount : 0;
}

/**
 * Every query behind the analysis workspace, for the applied (not draft) settings. Each result is
 * sticky, so changing a setting dims the panels while new figures load rather than blanking them.
 */
export function useAnalysis(applied: AnalysisSettings, hexRes: number) {
  const base = useBaseParams();
  const { writes } = useScope();
  const minCount = useMinCount(applied);

  const policy = useMemo(
    () => ({
      ...base,
      scope: sql.string(applied.scope),
      service: sql.string(applied.service),
      threshold: sql.int(applied.threshold),
      min_count: sql.int(minCount),
    }),
    [base, applied.scope, applied.service, applied.threshold, minCount]
  );
  const regional = useMemo(() => ({ ...policy, geo_level: sql.string(applied.geoLevel) }), [policy, applied.geoLevel]);

  const shapesParams = useMemo(
    () => ({ ...base, geo_level: sql.string(applied.geoLevel), scope: sql.string(applied.scope) }),
    [base, applied.geoLevel, applied.scope]
  );
  const shapes = useSticky(useAnalyticsQuery('region_shapes', shapesParams, { format: 'ARROW_STREAM' }));
  const outlines = useSticky(useAnalyticsQuery('state_outlines', base, { format: 'ARROW_STREAM' }));
  const access = useSticky(useRows('region_access', regional));
  const summary = useSticky(useRows('scope_summary', policy));
  const remoteness = useSticky(useRows('remoteness_access', policy));

  const sitesParams = useMemo(
    () => ({
      ...base,
      scope: sql.string(applied.scope),
      service: sql.string(applied.service),
      min_count: sql.int(minCount),
    }),
    [base, applied.scope, applied.service, minCount]
  );
  const sites = useSticky(useRows('service_sites', sitesParams));

  const wantHex = applied.layer === 'hexagons';
  const hexParams = useMemo(() => ({ ...policy, hex_res: sql.int(hexRes) }), [policy, hexRes]);
  const hex = useSticky(useAnalyticsQuery('hex_access', hexParams, { format: 'ARROW_STREAM', autoStart: wantHex }));

  const sitesJson = JSON.stringify(applied.sites.map((s) => ({ lon: s.lon, lat: s.lat })));
  const wantScenario = applied.sites.length > 0;
  const scenarioParams = useMemo(() => ({ ...regional, sites: sql.string(sitesJson) }), [regional, sitesJson]);
  const scenarioRaw = useRows('scenario_gain', scenarioParams, { autoStart: wantScenario });

  const notesParams = useMemo(
    () => ({
      ...base,
      service: sql.string(applied.service),
      geo_level: sql.string(applied.geoLevel),
      refresh: sql.string(writes),
    }),
    [base, applied.service, applied.geoLevel, writes]
  );
  const notes = useSticky(useRows('review_notes', notesParams));

  const shapeRows = useMemo(() => arrowRows<RegionShape>(shapes.data), [shapes.data]);
  const outlineRows = useMemo(() => arrowRows<StateOutline>(outlines.data), [outlines.data]);
  const hexRows = useMemo(() => (wantHex ? arrowRows<HexCell>(hex.data) : []), [hex.data, wantHex]);
  const accessRows = (access.data ?? []) as RegionAccess[];
  const notesByRegion = useMemo(
    () => new Map(((notes.data ?? []) as ReviewNoteRow[]).map((n) => [n.region_code, n])),
    [notes.data]
  );
  const scenarioRows = wantScenario ? ((scenarioRaw.data ?? []) as ScenarioRow[]) : [];

  return {
    minCount,
    shapes: { ...shapes, rows: shapeRows },
    outlines: { ...outlines, rows: outlineRows },
    access: { ...access, rows: accessRows },
    summary: { ...summary, row: ((summary.data ?? [])[0] ?? null) as ScopeSummary | null },
    remoteness: { ...remoteness, rows: (remoteness.data ?? []) as RemotenessRow[] },
    sites: { ...sites, rows: (sites.data ?? []) as ServiceSite[] },
    hex: { ...hex, rows: hexRows, enabled: wantHex, res: hexRes },
    scenario: {
      enabled: wantScenario,
      loading: wantScenario && scenarioRaw.loading,
      error: wantScenario ? scenarioRaw.error : null,
      total: scenarioRows.find((r) => r.region_code == null) ?? null,
      regions: scenarioRows.filter((r) => r.region_code != null),
    },
    notes: { ...notes, byRegion: notesByRegion },
  };
}

export type Analysis = ReturnType<typeof useAnalysis>;
