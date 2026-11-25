import type { QueryRegistry } from '@databricks/appkit-ui/react';

/** Row types come from the generated query registry (npm run typegen), never hand-written. */
export type OpsStatusRow = QueryRegistry['ops_status']['result'][number];
export type AlertRow = QueryRegistry['alert_queue']['result'][number];
export type RegisterRow = QueryRegistry['risk_register']['result'][number];
export type MovementRow = QueryRegistry['entity_movement']['result'][number];
export type TrendRow = QueryRegistry['signal_trend']['result'][number];
export type DecisionRow = QueryRegistry['recent_decisions']['result'][number];

/** What the review dialog needs, whether opened from the alert queue or the risk register. */
export interface ReviewTarget {
  assetId: number;
  plate: string;
  operator: string;
  riskType: string;
  primaryFactor: string;
  score: number;
  lastSeenTs: string | null;
  lastSeenLocation: string | null;
  recommendedAction: string;
  scores: {
    rest_window_anomaly_score: number | null;
    night_movement_score: number | null;
    recent_pattern_score: number | null;
    route_variance_score: number | null;
    mass_variance_score: number | null;
    defect_history_score: number | null;
  };
  /** Present only when the entity is in the alert queue (score at or above threshold). */
  alert?: {
    alertId: string;
    priority: number;
    severity: string;
    status: string;
    decidedBy: string | null;
    decidedTs: string | null;
    ageMinutes: number | null;
  };
}

const n = (v: unknown) => (v == null || v === '' ? null : Number(v));

export function scoresOf(row: AlertRow | RegisterRow): ReviewTarget['scores'] {
  return {
    rest_window_anomaly_score: n(row.rest_window_anomaly_score),
    night_movement_score: n(row.night_movement_score),
    recent_pattern_score: n(row.recent_pattern_score),
    route_variance_score: n(row.route_variance_score),
    mass_variance_score: n(row.mass_variance_score),
    defect_history_score: n(row.defect_history_score),
  };
}

export function fromAlert(row: AlertRow): ReviewTarget {
  return {
    assetId: Number(row.asset_id),
    plate: String(row.registration_plate),
    operator: String(row.operator_name),
    riskType: String(row.risk_type),
    primaryFactor: String(row.primary_factor),
    score: Number(row.risk_score),
    lastSeenTs: row.last_seen_ts == null ? null : String(row.last_seen_ts),
    lastSeenLocation: row.last_seen_location == null ? null : String(row.last_seen_location),
    recommendedAction: String(row.recommended_action),
    scores: scoresOf(row),
    alert: {
      alertId: String(row.alert_id),
      priority: Number(row.priority),
      severity: String(row.severity),
      status: String(row.status),
      decidedBy: row.decided_by == null ? null : String(row.decided_by),
      decidedTs: row.decided_ts == null ? null : String(row.decided_ts),
      ageMinutes: n(row.age_minutes),
    },
  };
}

export function fromRegister(row: RegisterRow, alert?: AlertRow): ReviewTarget {
  if (alert) return fromAlert(alert);
  return {
    assetId: Number(row.asset_id),
    plate: String(row.registration_plate),
    operator: String(row.operator_name),
    riskType: String(row.risk_type),
    primaryFactor: String(row.primary_factor),
    score: Number(row.risk_score),
    lastSeenTs: row.last_seen_ts == null ? null : String(row.last_seen_ts),
    lastSeenLocation: row.last_seen_location == null ? null : String(row.last_seen_location),
    recommendedAction: String(row.recommended_action),
    scores: scoresOf(row),
  };
}
