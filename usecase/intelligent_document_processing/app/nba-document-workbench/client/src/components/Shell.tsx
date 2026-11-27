import {
  BookOpenCheck,
  FileInput,
  FileSearch,
  Inbox,
  LayoutDashboard,
  Loader2,
  MessageSquareText,
  Moon,
  ScrollText,
  Sun,
  TrendingUp,
} from 'lucide-react';
import type { ReactNode } from 'react';

export type View = 'overview' | 'queue' | 'review' | 'intake' | 'ask' | 'register' | 'performance' | 'log';

const WORKSPACE: { view: View; label: string; icon: ReactNode; countKey?: 'queue' | 'intake' }[] = [
  { view: 'overview', label: 'Overview', icon: <LayoutDashboard aria-hidden="true" /> },
  { view: 'queue', label: 'Review queue', icon: <FileSearch aria-hidden="true" />, countKey: 'queue' },
  { view: 'intake', label: 'Intake', icon: <Inbox aria-hidden="true" />, countKey: 'intake' },
  { view: 'ask', label: 'Ask the AP data', icon: <MessageSquareText aria-hidden="true" /> },
];
const GOVERNANCE: { view: View; label: string; icon: ReactNode }[] = [
  { view: 'register', label: 'Document register', icon: <ScrollText aria-hidden="true" /> },
  { view: 'performance', label: 'Performance', icon: <TrendingUp aria-hidden="true" /> },
  { view: 'log', label: 'Decision log', icon: <BookOpenCheck aria-hidden="true" /> },
];

export function Sidebar({
  view,
  onNavigate,
  counts,
}: {
  view: View;
  onNavigate: (v: View) => void;
  counts: { queue: number | null; intake: number | null };
}) {
  const current = view === 'review' ? 'queue' : view;
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          DA
        </div>
        <div>
          <div className="brand-name">Document Assurance</div>
          <div className="brand-sub">Accounts payable workbench</div>
        </div>
      </div>
      <div className="nav-strip">
        <div className="nav-label" id="nav-workspace">
          Workspace
        </div>
        <nav className="nav" aria-labelledby="nav-workspace">
          {WORKSPACE.map((item) => (
            <button
              key={item.view}
              aria-current={current === item.view ? 'page' : undefined}
              onClick={() => onNavigate(item.view)}
            >
              {item.icon}
              {item.label}
              {item.countKey && counts[item.countKey] != null && (
                <span className="nav-count" aria-label={`${counts[item.countKey]} open`}>
                  {counts[item.countKey]}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="nav-label" id="nav-governance">
          Governance
        </div>
        <nav className="nav" aria-labelledby="nav-governance">
          {GOVERNANCE.map((item) => (
            <button
              key={item.view}
              aria-current={current === item.view ? 'page' : undefined}
              onClick={() => onNavigate(item.view)}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="sidebar-foot">
        <span className="classification">OFFICIAL</span>
        <div>
          Synthetic demonstration corpus
          <br />
          No write-back to the finance system
        </div>
      </div>
    </aside>
  );
}

export function Topbar({
  crumb,
  dark,
  onTheme,
  onIngest,
  ingest,
}: {
  crumb: string;
  dark: boolean;
  onTheme: () => void;
  onIngest: () => void;
  ingest: { enabled: boolean; running: boolean; label: string | null };
}) {
  return (
    <header className="topbar">
      <div className="crumb">
        Nation Building Authority / Accounts payable / <strong>{crumb}</strong>
      </div>
      <div className="top-actions">
        {ingest.running && ingest.label && (
          <span className="ingest-status hide-narrow" role="status">
            <Loader2 size={14} className="spin" aria-hidden="true" />
            {ingest.label}
          </span>
        )}
        <button
          className="button icon-button"
          onClick={onTheme}
          aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {dark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
        </button>
        <button
          className="button"
          onClick={onIngest}
          disabled={!ingest.enabled || ingest.running}
          title={ingest.enabled ? undefined : 'Ingestion is not configured for this deployment'}
        >
          <FileInput aria-hidden="true" />
          {ingest.running ? 'Ingesting' : 'Ingest documents'}
        </button>
      </div>
    </header>
  );
}
