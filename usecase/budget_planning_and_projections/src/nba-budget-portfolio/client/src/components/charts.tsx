import { useMemo, useState } from 'react';
import { bn, money, monthLabel, num, pct } from '../lib/format';

const W = 760;
const PAD = { top: 16, right: 20, bottom: 34, left: 52 };

function niceTicks(min: number, max: number, count = 5): number[] {
  const span = Math.max(max - min, 1e-9);
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (count * step) / span;
  const mult = err <= 0.15 ? 10 : err <= 0.35 ? 5 : err <= 0.75 ? 2 : 1;
  const s = step * mult;
  const ticks: number[] = [];
  for (let v = Math.floor(min / s) * s; v <= max + s * 0.5; v += s) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

type Series = { key: string; label: string; values: Array<number | null>; className: string; dashed?: boolean };

/** Annual line chart with straight segments (annual totals are not a continuous curve), an optional P10-P90
 *  band, shading where forecast exceeds capacity, and a per-year hover readout. Values in $bn. */
export function TrendChart({
  labels,
  series,
  band,
  gapBetween,
  height = 300,
  format = (v: number) => `$${v.toFixed(1)}bn`,
  ariaLabel,
}: {
  labels: string[];
  series: Series[];
  band?: { low: Array<number | null>; high: Array<number | null>; label: string };
  gapBetween?: { over: string; under: string };
  height?: number;
  format?: (v: number) => string;
  ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const all = [...series.flatMap((s) => s.values), ...(band ? [...band.low, ...band.high] : [])].filter((v): v is number => v !== null && Number.isFinite(v));
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all) : 1;
  const ticks = niceTicks(Math.max(0, lo - (hi - lo) * 0.25), hi + (hi - lo) * 0.08);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (labels.length <= 1 ? innerW / 2 : (i * innerW) / (labels.length - 1));
  const y = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin || 1)) * innerH;
  const path = (values: Array<number | null>) =>
    values.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(' L ');

  const over = gapBetween ? series.find((s) => s.key === gapBetween.over) : undefined;
  const under = gapBetween ? series.find((s) => s.key === gapBetween.under) : undefined;
  const gapPolys: string[] = [];
  if (over && under) {
    for (let i = 0; i < labels.length - 1; i++) {
      const a0 = over.values[i], a1 = over.values[i + 1], b0 = under.values[i], b1 = under.values[i + 1];
      if ([a0, a1, b0, b1].some((v) => v === null)) continue;
      const d0 = (a0 as number) - (b0 as number), d1 = (a1 as number) - (b1 as number);
      if (d0 <= 0 && d1 <= 0) continue;
      const pts: Array<[number, number]> = [];
      const cross = d0 !== d1 ? d0 / (d0 - d1) : 0;
      const xi = (t: number) => x(i) + t * (x(i + 1) - x(i));
      const lerp = (p: number, q: number, t: number) => p + t * (q - p);
      if (d0 > 0 && d1 > 0) {
        pts.push([x(i), y(a0 as number)], [x(i + 1), y(a1 as number)], [x(i + 1), y(b1 as number)], [x(i), y(b0 as number)]);
      } else if (d0 > 0) {
        pts.push([x(i), y(a0 as number)], [xi(cross), y(lerp(a0 as number, a1 as number, cross))], [x(i), y(b0 as number)]);
      } else {
        pts.push([xi(cross), y(lerp(a0 as number, a1 as number, cross))], [x(i + 1), y(a1 as number)], [x(i + 1), y(b1 as number)]);
      }
      gapPolys.push(pts.map((p) => p.join(',')).join(' '));
    }
  }
  const bandPath = band
    ? (() => {
        const top = band.high.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean);
        const bottom = band.low.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).reverse();
        return top.length > 1 ? `M ${top.join(' L ')} L ${bottom.join(' L ')} Z` : null;
      })()
    : null;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={ariaLabel} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="axis-label">{format(t)}</text>
          </g>
        ))}
        {labels.map((l, i) => (
          <text key={l} x={x(i)} y={height - 10} textAnchor="middle" className="axis-label">{l}</text>
        ))}
        {bandPath && <path d={bandPath} className="band" />}
        {gapPolys.map((p, i) => <polygon key={i} points={p} className="gap-area" />)}
        {series.map((s) => (
          <g key={s.key} className={s.className}>
            <path d={`M ${path(s.values)}`} className={`line ${s.dashed ? 'dashed' : ''}`} />
            {s.values.map((v, i) => (v === null ? null : <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : 3} className="dot" />))}
          </g>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="hover-line" />}
        {labels.map((l, i) => (
          <rect key={l} x={x(i) - innerW / Math.max(labels.length - 1, 1) / 2} y={PAD.top} width={innerW / Math.max(labels.length - 1, 1)} height={innerH}
            fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hover !== null && (
        <div className="chart-readout" role="status">
          <strong>{labels[hover]}</strong>
          {series.map((s) => s.values[hover] !== null && (
            <span key={s.key}><i className={`swatch ${s.className}`} />{s.label} {format(s.values[hover] as number)}</span>
          ))}
          {band && band.low[hover] !== null && <span><i className="swatch band" />{band.label} {format(band.low[hover] as number)}–{format(band.high[hover] as number)}</span>}
        </div>
      )}
      <div className="legend">
        {series.map((s) => <span key={s.key}><i className={`swatch ${s.className} ${s.dashed ? 'dashed' : ''}`} />{s.label}</span>)}
        {band && <span><i className="swatch band" />{band.label}</span>}
        {gapPolys.length > 0 && <span><i className="swatch gap" />Spend above deliverable capacity</span>}
      </div>
    </div>
  );
}

/** Plan -> recorded drivers -> forecast. Values in AUD m. */
export function Waterfall({ start, startLabel, steps, endLabel }: { start: number; startLabel: string; steps: Array<{ label: string; value: number }>; endLabel: string }) {
  const height = 280;
  const end = start + steps.reduce((a, s) => a + s.value, 0);
  let running = start;
  const bars = [
    { label: startLabel, from: 0, to: start, kind: 'total' as const, value: start },
    ...steps.map((s) => {
      const from = running;
      running += s.value;
      return { label: s.label, from, to: running, kind: s.value >= 0 ? ('up' as const) : ('down' as const), value: s.value };
    }),
    { label: endLabel, from: 0, to: end, kind: 'total' as const, value: end },
  ];
  const lows = bars.filter((b) => b.kind !== 'total').map((b) => Math.min(b.from, b.to));
  const minV = Math.min(start, end, ...lows);
  const maxV = Math.max(start, end, ...bars.map((b) => Math.max(b.from, b.to)));
  // Totals are drawn from a broken axis so the driver steps are legible; the axis labels say so.
  const floor = Math.max(0, minV - (maxV - minV) * 1.2);
  const ticks = niceTicks(floor, maxV);
  const yMin = ticks[0], yMax = ticks[ticks.length - 1];
  const innerW = W - PAD.left - PAD.right, innerH = height - PAD.top - PAD.bottom;
  const slot = innerW / bars.length;
  const y = (v: number) => PAD.top + innerH - ((Math.max(v, yMin) - yMin) / (yMax - yMin || 1)) * innerH;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`Variance bridge from ${startLabel} to ${endLabel}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="axis-label">{bn(t)}</text>
          </g>
        ))}
        {bars.map((b, i) => {
          const top = y(Math.max(b.from, b.to));
          const h = Math.max(2, Math.abs(y(b.from) - y(b.to)));
          const cx = PAD.left + slot * i + slot / 2;
          return (
            <g key={b.label}>
              <rect x={cx - slot * 0.32} y={b.kind === 'total' ? y(b.to) : top} width={slot * 0.64} height={b.kind === 'total' ? y(yMin) - y(b.to) : h} className={`wf-${b.kind}`} rx={3} />
              {i < bars.length - 1 && <line x1={cx + slot * 0.32} x2={cx + slot * 0.68} y1={y(b.to)} y2={y(b.to)} className="wf-connector" />}
              <text x={cx} y={(b.kind === 'total' ? y(b.to) : top) - 6} textAnchor="middle" className="wf-value">
                {b.kind === 'total' ? bn(b.value) : money(b.value, true)}
              </text>
              <text x={cx} y={height - 10} textAnchor="middle" className="axis-label">{b.label}</text>
            </g>
          );
        })}
      </svg>
      <p className="chart-note">Axis starts at {bn(yMin)} so driver movements are visible.</p>
    </div>
  );
}

export type HeatCell = { categoryId: string; category: string; fy: string; utilisation: number; baseline: number; status: string; unit: string; gapValue: number };

export function Heatmap({ cells, years, onSelect, selected }: { cells: HeatCell[]; years: string[]; onSelect: (cell: HeatCell) => void; selected?: string }) {
  const categories = useMemo(() => {
    const peak = new Map<string, number>();
    for (const c of cells) peak.set(c.category, Math.max(peak.get(c.category) ?? 0, c.utilisation));
    return [...peak.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
  }, [cells]);
  const lookup = useMemo(() => new Map(cells.map((c) => [`${c.category}|${c.fy}`, c])), [cells]);
  return (
    <div className="heatmap" role="grid" aria-label="Utilisation of each delivery input by financial year">
      <div className="heat-row heat-head" role="row">
        <span role="columnheader">Delivery input</span>
        {years.map((y) => <span role="columnheader" key={y}>{y}</span>)}
      </div>
      {categories.map((category) => (
        <div className="heat-row" role="row" key={category}>
          <span role="rowheader" className="heat-label">{category}</span>
          {years.map((fy) => {
            const cell = lookup.get(`${category}|${fy}`);
            if (!cell) return <span key={fy} />;
            const level = cell.utilisation > 100 ? 'breach' : cell.utilisation >= 90 ? 'constrained' : cell.utilisation >= 75 ? 'high' : cell.utilisation >= 55 ? 'mid' : 'low';
            const delta = cell.utilisation - cell.baseline;
            const key = `${cell.categoryId}|${fy}`;
            return (
              <button key={fy} role="gridcell" className={`heat-cell ${level} ${selected === key ? 'selected' : ''}`} onClick={() => onSelect(cell)}
                aria-label={`${category} ${fy}: ${pct(cell.utilisation)} utilised, ${cell.status}`}>
                <strong>{pct(cell.utilisation, Math.abs(cell.utilisation - 100) < 0.5 ? 1 : 0)}</strong>
                {Math.abs(delta) >= 1 && <small>{delta > 0 ? '▲' : '▼'}{Math.abs(delta).toFixed(0)} vs base</small>}
              </button>
            );
          })}
        </div>
      ))}
      <div className="heat-key">
        <span><i className="heat-cell low" />&lt;55%</span><span><i className="heat-cell mid" />55–75%</span><span><i className="heat-cell high" />75–90%</span>
        <span><i className="heat-cell constrained" />Constrained ≥90%</span><span><i className="heat-cell breach" />Breach &gt;100%</span>
      </div>
    </div>
  );
}

/** Monthly phasing: actual columns for closed months, plan (dashed) and forecast lines. Values in AUD m. */
export function PhasingChart({ rows }: { rows: Array<{ month: string; plan: number; forecast: number; actual: number; isActual: boolean }> }) {
  const height = 240;
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...rows.map((r) => Math.max(r.plan, r.forecast, r.actual)));
  const ticks = niceTicks(0, max * 1.08, 4);
  const yMax = ticks[ticks.length - 1];
  const innerW = W - PAD.left - PAD.right, innerH = height - PAD.top - PAD.bottom;
  const step = innerW / Math.max(rows.length, 1);
  const x = (i: number) => PAD.left + step * i + step / 2;
  const y = (v: number) => PAD.top + innerH - (v / (yMax || 1)) * innerH;
  const line = (key: 'plan' | 'forecast') => rows.map((r, i) => `${x(i)},${y(r[key])}`).join(' L ');
  const firstForecast = rows.findIndex((r) => !r.isActual);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Monthly plan, forecast and actual expenditure" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="axis-label">{money(t)}</text>
          </g>
        ))}
        {firstForecast > 0 && <line x1={x(firstForecast) - step / 2} x2={x(firstForecast) - step / 2} y1={PAD.top} y2={PAD.top + innerH} className="today-line" />}
        {rows.map((r, i) => r.isActual && <rect key={r.month} x={x(i) - step * 0.35} y={y(r.actual)} width={step * 0.7} height={Math.max(0, y(0) - y(r.actual))} className="actual-bar" />)}
        <path d={`M ${line('plan')}`} className="line plan-line dashed" />
        <path d={`M ${line('forecast')}`} className="line forecast-line" />
        {rows.map((r, i) => (i % 12 === 0 ? <text key={r.month} x={x(i)} y={height - 10} textAnchor="start" className="axis-label">{monthLabel(r.month)}</text> : null))}
        {rows.map((r, i) => <rect key={`h${r.month}`} x={x(i) - step / 2} y={PAD.top} width={step} height={innerH} fill="transparent" onMouseEnter={() => setHover(i)} />)}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="hover-line" />}
      </svg>
      {hover !== null && rows[hover] && (
        <div className="chart-readout" role="status">
          <strong>{monthLabel(rows[hover].month)}</strong>
          <span><i className="swatch plan dashed" />Plan {money(rows[hover].plan)}</span>
          <span><i className="swatch forecast" />{rows[hover].isActual ? 'Actual' : 'Forecast'} {money(rows[hover].isActual ? rows[hover].actual : rows[hover].forecast)}</span>
        </div>
      )}
      <div className="legend">
        <span><i className="swatch actual" />Actual (closed months)</span>
        <span><i className="swatch forecast" />Forecast</span>
        <span><i className="swatch plan dashed" />Endorsed plan</span>
      </div>
    </div>
  );
}

export function Meter({ value, max = 120, threshold = 100 }: { value: number; max?: number; threshold?: number }) {
  const v = Math.min(num(value), max);
  const level = value > threshold ? 'risk' : value >= 90 ? 'warn' : '';
  return (
    <div className="meter" aria-hidden="true">
      <div className={`meter-fill ${level}`} style={{ width: `${(v / max) * 100}%` }} />
      <div className="meter-threshold" style={{ left: `${(threshold / max) * 100}%` }} />
    </div>
  );
}
