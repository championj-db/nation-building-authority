import { describe, expect, it } from 'vitest';
import { analysisSettingsSchema, briefSchema, resolveMinCount, resolveSchema, reviewNoteSchema } from './contracts';

const settings = {
  service: 'public_hospital',
  geoLevel: 'sa4',
  scope: 'NSW',
  threshold: 45,
  suppress: true,
  boundaries: true,
  layer: 'regions',
  sites: [{ lon: 149.1, lat: -31.5 }],
};

describe('contracts', () => {
  it('accepts valid analysis settings and rejects out-of-range ones', () => {
    expect(analysisSettingsSchema.safeParse(settings).success).toBe(true);
    expect(analysisSettingsSchema.safeParse({ ...settings, threshold: 400 }).success).toBe(false);
    expect(analysisSettingsSchema.safeParse({ ...settings, scope: 'XX' }).success).toBe(false);
    expect(analysisSettingsSchema.safeParse({ ...settings, sites: Array(6).fill({ lon: 150, lat: -30 }) }).success).toBe(false);
    // a proposed site outside Australia's extent is refused
    expect(analysisSettingsSchema.safeParse({ ...settings, sites: [{ lon: 10, lat: 50 }] }).success).toBe(false);
  });

  it('rejects region codes that could reach SQL', () => {
    const note = { service: 'urgent_care', geoLevel: 'sa2', regionName: 'Dubbo', thresholdKm: 30, evidenceStatus: 'validated' };
    expect(reviewNoteSchema.safeParse({ ...note, regionCode: '105011095' }).success).toBe(true);
    expect(reviewNoteSchema.safeParse({ ...note, regionCode: "1'; DROP TABLE x" }).success).toBe(false);
  });

  it('requires a purpose before a brief can be prepared', () => {
    const findings = {
      scopeLabel: 'NSW', serviceLabel: 'Public hospitals', geographyLabel: 'SA4', persons: 1, personsBeyond: 1,
      shareBeyond: 1, persons65Beyond: null, householdsNoVehicleBeyond: null, medianKm: 3, regionsBeyond: 0,
      regionsTotal: 1, priorities: [], scenario: null, dataRefreshed: null,
    };
    const brief = { title: 'Access', policyQuestion: 'short', accessBasis: 'Planning', audience: 'Exec', settings, findings };
    expect(briefSchema.safeParse(brief).success).toBe(false);
    expect(briefSchema.safeParse({ ...brief, policyQuestion: 'Where should a new clinic go?' }).success).toBe(true);
  });

  it('only interpolates plain Unity Catalog identifiers', () => {
    expect(resolveSchema({ DATABRICKS_CATALOG: 'main', DATABRICKS_SCHEMA: 'geo_1' })).toEqual({ catalog: 'main', schema: 'geo_1' });
    expect(() => resolveSchema({ DATABRICKS_CATALOG: 'main`; --', DATABRICKS_SCHEMA: 'x' })).toThrow();
  });

  it('keeps the disclosure threshold within a sane range', () => {
    expect(resolveMinCount({})).toBe(10);
    expect(resolveMinCount({ SUPPRESSION_MIN_COUNT: '5' })).toBe(5);
    expect(resolveMinCount({ SUPPRESSION_MIN_COUNT: '0' })).toBe(10);
  });
});
