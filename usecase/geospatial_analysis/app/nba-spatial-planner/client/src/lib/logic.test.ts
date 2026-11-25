import { describe, expect, it } from 'vitest';
import { people, km, pct } from './format';
import { fitViewBox, haversineKm, makeProjection } from './geo';
import { defaultEvidence, priorities, recommendedStep, type RegionAccess } from './model';
import { DEFAULT_SETTINGS, samePolicy, settingsFromSearch, settingsToSearch } from './settings';

const region = (over: Partial<RegionAccess>): RegionAccess => ({
  region_code: '1',
  region_name: 'A',
  state_abbr: 'NSW',
  ra_class: null,
  persons: 1000,
  access_class: 'within',
  median_km: 5,
  p90_km: 9,
  persons_beyond: 0,
  beyond_suppressed: false,
  share_beyond: 0,
  persons_65_beyond: 0,
  households_no_vehicle_beyond: 0,
  ...over,
});

describe('settings in the URL', () => {
  it('round-trips, including proposed sites', () => {
    const s = { ...DEFAULT_SETTINGS, scope: 'QLD' as const, threshold: 60, sites: [{ lon: 145.7712, lat: -16.9186 }] };
    const back = settingsFromSearch(settingsToSearch(s, 'assurance'));
    expect(back.tab).toBe('assurance');
    expect(back.settings).toEqual(s);
  });
  it('falls back to defaults on a tampered link', () => {
    expect(settingsFromSearch('?t=9999&scope=NOPE').settings).toEqual(DEFAULT_SETTINGS);
  });
  it('treats display options as outside the policy', () => {
    expect(samePolicy(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, layer: 'hexagons', boundaries: false })).toBe(true);
    expect(samePolicy(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS, threshold: 50 })).toBe(false);
  });
});

describe('projection', () => {
  it('maps kilometres to map units at the reference latitude', () => {
    const p = makeProjection({ xmin: 150, xmax: 152, ymin: -34, ymax: -33 });
    const [x0, y0] = p.project(150.5, -33.5);
    const [x1, y1] = p.project(151.5, -33.5);
    const east = haversineKm({ lon: 150.5, lat: -33.5 }, { lon: 151.5, lat: -33.5 });
    expect(Math.abs(Math.hypot(x1 - x0, y1 - y0) - east)).toBeLessThan(1);
    const [lon, lat] = p.unproject(...p.project(151.2, -33.87));
    expect(lon).toBeCloseTo(151.2, 6);
    expect(lat).toBeCloseTo(-33.87, 6);
  });
  it('fits a view box to the requested aspect', () => {
    const p = makeProjection({ xmin: 140, xmax: 150, ymin: -38, ymax: -28 });
    const v = fitViewBox({ xmin: 140, xmax: 150, ymin: -38, ymax: -28 }, p, 2);
    expect(v.w / v.h).toBeCloseTo(2, 6);
  });
});

describe('formatting and rules', () => {
  it('never prints a suppressed count as a number', () => {
    expect(people(null, 10)).toBe('<10');
    expect(people(12345, 10)).toBe('12,345');
    expect(km(300)).toBe('300+ km');
    expect(pct(0.0004)).toBe('<0.1%');
  });
  it('ranks beyond before near, by people beyond', () => {
    const rows = [
      region({ region_code: 'n', access_class: 'near', persons_beyond: 9000 }),
      region({ region_code: 'b1', access_class: 'beyond', persons_beyond: 100 }),
      region({ region_code: 'b2', access_class: 'beyond', persons_beyond: 5000 }),
      region({ region_code: 'w', access_class: 'within' }),
    ];
    expect(priorities(rows).map((r) => r.region_code)).toEqual(['b2', 'b1', 'n']);
  });
  it('recommends a scenario only where enough people are beyond', () => {
    expect(recommendedStep(region({ access_class: 'beyond', persons_beyond: 5000 }))).toMatch(/scenario/);
    expect(recommendedStep(region({ access_class: 'beyond', persons_beyond: 50 }))).toMatch(/outreach/);
    expect(defaultEvidence('beyond')).toBe('needs_validation');
  });
});
