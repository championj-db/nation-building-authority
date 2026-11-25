import type { QueryRegistry } from '@databricks/appkit-ui/react';

/** Row types come from the generated query registry (npm run typegen), never hand-written. */
export type OpsStatusRow = QueryRegistry['ops_status']['result'][number];
export type SectorRow = QueryRegistry['sector_status']['result'][number];
export type IncidentRow = QueryRegistry['incident_queue']['result'][number];
export type ImpactRow = QueryRegistry['incident_impact']['result'][number];
export type NetworkAssetRow = QueryRegistry['network_assets']['result'][number];
export type HazardRow = QueryRegistry['hazards']['result'][number];
export type TelemetryRow = QueryRegistry['asset_telemetry']['result'][number];
export type RegisterRow = QueryRegistry['asset_register']['result'][number];
export type DecisionRow = QueryRegistry['recent_decisions']['result'][number];

/** Group downstream impact rows by incident, for the dialog and the map's cascade lines. */
export function impactsByIncident(rows: ImpactRow[] | null): Map<string, ImpactRow[]> {
  const map = new Map<string, ImpactRow[]>();
  for (const row of rows ?? []) {
    const key = String(row.incident_id);
    const list = map.get(key);
    if (list) list.push(row);
    else map.set(key, [row]);
  }
  return map;
}
