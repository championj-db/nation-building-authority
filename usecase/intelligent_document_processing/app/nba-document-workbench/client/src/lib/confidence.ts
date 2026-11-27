/**
 * Confidence is a routing control, not a probability (PRODUCT.md). The workbench shows it as a
 * band with its reason; the score itself appears only as a tooltip and in the Performance tables.
 */
export const REVIEW_THRESHOLD = 0.85;

export type Band = 'confident' | 'low' | 'not_on_page' | 'missing';

export const BAND_LABELS: Record<Band, string> = {
  confident: 'Confident',
  low: 'Low',
  not_on_page: 'Not on page',
  missing: 'Missing',
};

export function bandOf(f: { value: string | null; grounded: boolean; routing_confidence: number }): Band {
  if (f.value == null || f.value === '') return 'missing';
  if (!f.grounded) return 'not_on_page';
  return f.routing_confidence < REVIEW_THRESHOLD ? 'low' : 'confident';
}

export function scoreTitle(score: number | null | undefined): string {
  return score == null
    ? 'No routing score'
    : `Routing score ${score.toFixed(2)} (review below ${REVIEW_THRESHOLD}). A routing control, not a probability.`;
}
