import { analysisSettingsSchema, GEO_LEVELS, SCOPES, SERVICES, type AnalysisSettings } from '../../../shared/contracts';

export type { AnalysisSettings };
export type ServiceType = (typeof SERVICES)[number];
export type GeoLevel = (typeof GEO_LEVELS)[number];
export type Scope = (typeof SCOPES)[number];
export type ProposedSite = AnalysisSettings['sites'][number];

export const GEO_LEVEL_LABELS: Record<GeoLevel, string> = {
  sa4: 'Planning regions (SA4)',
  sa3: 'Service districts (SA3)',
  sa2: 'Statistical areas (SA2)',
  lga: 'Local government areas',
  ra: 'Remoteness areas',
  state: 'States and territories',
};

/** Short plural noun for counts ("2 of 6 regions"). */
export const GEO_LEVEL_NOUN: Record<GeoLevel, string> = {
  sa4: 'regions',
  sa3: 'districts',
  sa2: 'areas',
  lga: 'LGAs',
  ra: 'remoteness areas',
  state: 'jurisdictions',
};

export const SCOPE_LABELS: Record<Scope, string> = {
  AUS: 'Australia',
  NSW: 'New South Wales',
  VIC: 'Victoria',
  QLD: 'Queensland',
  SA: 'South Australia',
  WA: 'Western Australia',
  TAS: 'Tasmania',
  NT: 'Northern Territory',
  ACT: 'Australian Capital Territory',
  OT: 'Other Territories',
};

/** Fallback labels until the service catalogue loads. */
export const SERVICE_LABELS: Record<ServiceType, string> = {
  public_hospital: 'Public hospitals',
  urgent_care: 'Medicare Urgent Care Clinics',
  residential_aged_care: 'Residential aged care',
  ambulance_station: 'Ambulance stations',
};

export const DEFAULT_SETTINGS: AnalysisSettings = {
  service: 'public_hospital',
  geoLevel: 'sa4',
  scope: 'AUS',
  threshold: 45,
  suppress: true,
  boundaries: true,
  layer: 'regions',
  sites: [],
};

export const THRESHOLD_SLIDER = { min: 10, max: 100, step: 5 } as const;

/** Policy settings are drafted then applied with "Run analysis"; display options apply at once. */
export const POLICY_KEYS = ['service', 'geoLevel', 'scope', 'threshold', 'suppress'] as const;

export function samePolicy(a: AnalysisSettings, b: AnalysisSettings) {
  return POLICY_KEYS.every((key) => a[key] === b[key]);
}

/** Settings live in the URL so any view is a shareable link. */
export function settingsToSearch(settings: AnalysisSettings, tab: string) {
  const params = new URLSearchParams();
  params.set('tab', tab);
  params.set('service', settings.service);
  params.set('geo', settings.geoLevel);
  params.set('scope', settings.scope);
  params.set('t', String(settings.threshold));
  if (!settings.suppress) params.set('suppress', '0');
  if (!settings.boundaries) params.set('boundaries', '0');
  if (settings.layer !== 'regions') params.set('layer', settings.layer);
  if (settings.sites.length) {
    params.set('sites', settings.sites.map((s) => `${s.lon.toFixed(4)},${s.lat.toFixed(4)}`).join(';'));
  }
  return `?${params.toString()}`;
}

export function settingsFromSearch(search: string): { settings: AnalysisSettings; tab: string } {
  const params = new URLSearchParams(search);
  const sites = (params.get('sites') ?? '')
    .split(';')
    .filter(Boolean)
    .map((pair) => {
      const [lon, lat] = pair.split(',').map(Number);
      return { lon: lon ?? NaN, lat: lat ?? NaN };
    });
  const candidate = {
    service: params.get('service') ?? DEFAULT_SETTINGS.service,
    geoLevel: params.get('geo') ?? DEFAULT_SETTINGS.geoLevel,
    scope: params.get('scope') ?? DEFAULT_SETTINGS.scope,
    threshold: Number(params.get('t') ?? DEFAULT_SETTINGS.threshold),
    suppress: params.get('suppress') !== '0',
    boundaries: params.get('boundaries') !== '0',
    layer: params.get('layer') ?? DEFAULT_SETTINGS.layer,
    sites,
  };
  const parsed = analysisSettingsSchema.safeParse(candidate);
  const tab = params.get('tab') ?? 'analysis';
  return {
    settings: parsed.success ? parsed.data : { ...DEFAULT_SETTINGS },
    tab: ['analysis', 'pipeline', 'assurance'].includes(tab) ? tab : 'analysis',
  };
}

/** Parse settings persisted by a saved view or brief; null if they no longer validate. */
export function parseStoredSettings(raw: unknown): AnalysisSettings | null {
  let value = raw;
  if (typeof raw === 'string') {
    try {
      value = JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }
  const parsed = analysisSettingsSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/**
 * Hexagon resolution for the H3 layer, from how much of the map is in view (km across): coarse
 * when zoomed out so cells stay legible, finer as the officer zooms in. Capped per scope so a
 * national view never requests tens of thousands of fine cells.
 */
export function hexResolution(scope: Scope, viewWidthKm: number) {
  const res = viewWidthKm > 2500 ? 4 : viewWidthKm > 800 ? 5 : viewWidthKm > 250 ? 6 : 7;
  return scope === 'AUS' ? Math.min(Math.max(res, 4), 5) : Math.min(Math.max(res, 5), 7);
}
