import { useEffect, useState } from 'react';
import type { Analysis } from '../lib/analysis';
import { buildFindings, parseFindings, type BriefRow, type Findings } from '../lib/briefs';
import { postJson, useScope } from '../lib/data';
import { dateTime, km, officerName, people, pct } from '../lib/format';
import { ACCESS_CLASS_LABEL, EVIDENCE_LABEL, type AccessClass, type EvidenceStatus } from '../lib/model';
import { SCOPE_LABELS, parseStoredSettings, settingsToSearch, type AnalysisSettings } from '../lib/settings';
import { Dialog, ErrorNotice, useToast } from './primitives';

export type BriefMode = { kind: 'prepare' } | { kind: 'view'; briefId: string } | null;

interface Props {
  mode: BriefMode;
  analysis: Analysis;
  settings: AnalysisSettings;
  serviceLabel: string;
  refreshed: string | null;
  briefs: BriefRow[];
  onClose: () => void;
  onPrepared: (briefId: string) => void;
}

const ACCESS_BASES = [
  'Service planning under the department’s functions',
  'Ministerial or executive briefing request',
  'Inter-agency planning agreement',
];

export function BriefDialog({ mode, analysis, settings, serviceLabel, refreshed, briefs, onClose, onPrepared }: Props) {
  const toast = useToast();
  const { bumpWrites, user } = useScope();
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [basis, setBasis] = useState(ACCESS_BASES[0] ?? '');
  const [audience, setAudience] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode?.kind !== 'prepare') return;
    setTitle(`Access to ${serviceLabel.toLowerCase()} in ${SCOPE_LABELS[settings.scope]}`);
    setQuestion('');
    setAudience('');
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode?.kind]);

  const brief = mode?.kind === 'view' ? briefs.find((b) => b.brief_id === mode.briefId) : undefined;
  const prepare = async () => {
    setBusy(true);
    setError(null);
    try {
      const findings = buildFindings(analysis, settings, serviceLabel, refreshed);
      const { briefId } = await postJson<{ briefId: string }>('/api/briefs', {
        title,
        policyQuestion: question,
        accessBasis: basis,
        audience,
        settings,
        findings,
      });
      bumpWrites();
      toast('Brief prepared and its purpose recorded. It needs officer sign-off before external circulation.');
      onPrepared(briefId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The brief was not prepared');
    } finally {
      setBusy(false);
    }
  };
  const signOff = async (id: string) => {
    setBusy(true);
    try {
      await postJson(`/api/briefs/${id}/sign-off`);
      bumpWrites();
      toast('Brief signed off for circulation.');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Sign-off was not recorded', 'error');
    } finally {
      setBusy(false);
    }
  };

  if (mode?.kind === 'prepare') {
    const blocked = !settings.suppress;
    const preview = buildFindings(analysis, settings, serviceLabel, refreshed);
    return (
      <Dialog
        open
        wide
        onClose={onClose}
        title="Prepare decision brief"
        subtitle="Record the purpose first. The figures are snapshotted as they stand now."
        footer={
          <>
            <button type="button" className="button" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="button primary"
              disabled={
                busy || blocked || question.trim().length < 10 || audience.trim().length < 3 || !analysis.summary.row
              }
              onClick={() => void prepare()}
            >
              {busy ? 'Preparing…' : 'Record purpose and prepare'}
            </button>
          </>
        }
      >
        {blocked && (
          <div style={{ marginBottom: 16 }}>
            <ErrorNotice
              title="Small-count suppression is off"
              message="Turn suppression on and run the analysis again before preparing a brief."
            />
          </div>
        )}
        <div className="field">
          <label htmlFor="brief-title">Title</label>
          <input
            id="brief-title"
            type="text"
            value={title}
            maxLength={140}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="brief-question">Policy question</label>
          <textarea
            id="brief-question"
            value={question}
            maxLength={600}
            placeholder="e.g. Which planning regions should be prioritised for a new urgent care clinic in the next budget cycle?"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <small>At least 10 characters. Shown at the top of the brief.</small>
        </div>
        <div className="field">
          <label htmlFor="brief-basis">Access basis</label>
          <select id="brief-basis" value={basis} onChange={(e) => setBasis(e.target.value)}>
            {ACCESS_BASES.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="brief-audience">Intended audience</label>
          <input
            id="brief-audience"
            type="text"
            value={audience}
            maxLength={200}
            placeholder="e.g. Deputy Secretary, Health Services Group"
            onChange={(e) => setAudience(e.target.value)}
          />
        </div>
        {error && <ErrorNotice title="Not prepared" message={error} />}
        <h3 className="section-title">Preview</h3>
        <div className="notice" style={{ marginTop: 8 }}>
          <BriefBody
            findings={preview}
            settings={settings}
            minCount={analysis.minCount}
            meta={{
              title,
              question: question || '—',
              basis,
              audience: audience || '—',
              preparedBy: user,
              preparedTs: null,
              status: 'draft',
              signedOffBy: null,
              signedOffTs: null,
            }}
          />
        </div>
      </Dialog>
    );
  }

  if (mode?.kind === 'view') {
    const findings = brief ? parseFindings(brief.findings) : null;
    const stored = brief ? parseStoredSettings(brief.settings) : null;
    return (
      <Dialog
        open
        wide
        className="print-root"
        onClose={onClose}
        title={brief?.title ?? 'Decision brief'}
        subtitle={brief ? `Prepared ${dateTime(brief.prepared_ts)}` : 'Loading…'}
        footer={
          brief && (
            <>
              {stored && (
                <a className="button" href={settingsToSearch(stored, 'analysis')}>
                  Open analysis
                </a>
              )}
              {brief.status === 'draft' && (
                <button type="button" className="button" disabled={busy} onClick={() => void signOff(brief.brief_id)}>
                  Sign off for circulation
                </button>
              )}
              <button type="button" className="button primary" onClick={() => window.print()}>
                Print or save PDF
              </button>
            </>
          )
        }
      >
        {!brief ? (
          <p className="muted">
            <span className="spinner" aria-hidden="true" />
            Loading brief…
          </p>
        ) : !findings || !stored ? (
          <ErrorNotice
            title="This brief cannot be displayed"
            message="Its stored figures no longer match the current format."
          />
        ) : (
          <BriefBody
            findings={findings}
            settings={stored}
            minCount={analysis.minCount || 10}
            meta={{
              title: brief.title,
              question: brief.policy_question,
              basis: brief.access_basis,
              audience: brief.audience,
              preparedBy: brief.prepared_by,
              preparedTs: brief.prepared_ts,
              status: brief.status,
              signedOffBy: brief.signed_off_by,
              signedOffTs: brief.signed_off_ts,
            }}
          />
        )}
      </Dialog>
    );
  }
  return null;
}

interface Meta {
  title: string;
  question: string;
  basis: string;
  audience: string;
  preparedBy: string | null;
  preparedTs: string | null;
  status: 'draft' | 'signed_off';
  signedOffBy: string | null;
  signedOffTs: string | null;
}

function BriefBody({
  findings,
  settings,
  minCount,
  meta,
}: {
  findings: Findings;
  settings: AnalysisSettings;
  minCount: number;
  meta: Meta;
}) {
  return (
    <article className="brief-doc">
      <span className={`watermark${meta.status === 'signed_off' ? ' ok' : ''}`}>
        {meta.status === 'signed_off'
          ? `Signed off by ${officerName(meta.signedOffBy)}`
          : 'Draft · not for circulation'}
      </span>
      <h2>{meta.title}</h2>
      <p className="muted">
        {findings.serviceLabel} · {findings.scopeLabel} · {findings.geographyLabel} · {settings.threshold} km
        straight-line threshold
      </p>
      <h3>Policy question</h3>
      <p>{meta.question}</p>
      <h3>Headline findings</h3>
      <div className="brief-figures">
        <div>
          <div className="metric-label">People beyond {settings.threshold} km</div>
          <div className="metric-value">{people(findings.personsBeyond, minCount)}</div>
          <span className="metric-note">{pct(findings.shareBeyond)} of modelled residents</span>
        </div>
        <div>
          <div className="metric-label">Regions beyond threshold</div>
          <div className="metric-value">
            {findings.regionsBeyond} of {findings.regionsTotal}
          </div>
          <span className="metric-note">Median resident beyond {settings.threshold} km</span>
        </div>
        <div>
          <div className="metric-label">Priority cohorts beyond</div>
          <div className="metric-value">{people(findings.persons65Beyond, minCount)}</div>
          <span className="metric-note">
            aged 65+ · {people(findings.householdsNoVehicleBeyond, minCount)} households without a car
          </span>
        </div>
      </div>
      {findings.scenario && (
        <p style={{ marginTop: 12 }}>
          A scenario adding {findings.scenario.sites} proposed site{findings.scenario.sites === 1 ? '' : 's'} would
          bring an estimated <strong>{people(findings.scenario.personsGained, minCount)}</strong> people within the
          threshold.
        </p>
      )}
      <h3>Review priorities</h3>
      {findings.priorities.length === 0 ? (
        <p className="muted">No regions are beyond or near the threshold.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>Access class</th>
              <th className="number">Median distance</th>
              <th className="number">Beyond threshold</th>
              <th>Evidence status</th>
            </tr>
          </thead>
          <tbody>
            {findings.priorities.map((p) => (
              <tr key={p.regionName}>
                <td>{p.regionName}</td>
                <td>{ACCESS_CLASS_LABEL[p.accessClass as AccessClass] ?? p.accessClass}</td>
                <td className="number">{km(p.medianKm)}</td>
                <td className="number">
                  {people(p.personsBeyond, minCount)} ({pct(p.shareBeyond, 0)})
                </td>
                <td>
                  {p.evidenceStatus ? (EVIDENCE_LABEL[p.evidenceStatus as EvidenceStatus] ?? p.evidenceStatus) : '–'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>Purpose and assurance</h3>
      <dl className="kv" style={{ fontSize: 'var(--text-sm)', gridTemplateColumns: 'auto 1fr' }}>
        <dt>Access basis</dt>
        <dd style={{ textAlign: 'left', fontFamily: 'inherit' }}>{meta.basis}</dd>
        <dt>Audience</dt>
        <dd style={{ textAlign: 'left', fontFamily: 'inherit' }}>{meta.audience}</dd>
        <dt>Prepared by</dt>
        <dd style={{ textAlign: 'left', fontFamily: 'inherit' }}>
          {officerName(meta.preparedBy)}
          {meta.preparedTs ? `, ${dateTime(meta.preparedTs)}` : ''}
        </dd>
        <dt>Sign-off</dt>
        <dd style={{ textAlign: 'left', fontFamily: 'inherit' }}>
          {meta.status === 'signed_off'
            ? `${officerName(meta.signedOffBy)}, ${dateTime(meta.signedOffTs)}`
            : 'Required before external circulation'}
        </dd>
        <dt>Data refreshed</dt>
        <dd style={{ textAlign: 'left', fontFamily: 'inherit' }}>{findings.dataRefreshed ?? '–'}</dd>
      </dl>
      <p className="xs muted" style={{ marginTop: 16 }}>
        Household locations are wholly synthetic, distributed in proportion to the ABS estimated resident population;
        counts under {minCount} are suppressed. Distances are straight-line to the nearest site, not road travel.
        Boundaries and population: Australian Bureau of Statistics, CC BY 4.0. Service locations: Department of Health,
        Disability and Ageing and Geoscience Australia, CC BY 4.0. Concept prototype; not for operational use.
      </p>
    </article>
  );
}
