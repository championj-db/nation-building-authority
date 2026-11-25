import { useState } from 'react';
import { createBrowserRouter, Link, NavLink, Outlet, RouterProvider, useLocation } from 'react-router';
import { Button, Sheet, SheetContent, SheetHeader, SheetTitle, useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { BarChart3, BookOpenCheck, Database, FileText, Fingerprint, Menu } from 'lucide-react';
import { ConfigProvider, useConfig, useDocumentTitle } from './lib/api';
import { num } from './lib/format';
import { EmptyState, ErrorState } from './components/common';
import { OverviewPage } from './pages/Overview';
import { ObligationsPage } from './pages/Obligations';
import { EvidencePage } from './pages/Evidence';
import { ReportsPage } from './pages/Reports';
import { AuditPage } from './pages/Audit';

const nav = [
  { to: '/', label: 'Overview', icon: BarChart3, badge: null },
  { to: '/obligations', label: 'Obligations', icon: BookOpenCheck, badge: null },
  { to: '/evidence', label: 'Evidence', icon: Database, badge: 'review' },
  { to: '/reports', label: 'Reports', icon: FileText, badge: null },
  { to: '/audit', label: 'Audit trail', icon: Fingerprint, badge: null },
] as const;

function NavLinks({ onNavigate, reviewCount }: { onNavigate?: () => void; reviewCount: number | null }) {
  return (
    <nav aria-label="Workspace">
      <ul className="nav-list">
        {nav.map(({ to, label, icon: Icon, badge }) => (
          <li key={to}>
            <NavLink to={to} end={to === '/'} onClick={onNavigate} className="nav-link">
              <Icon size={18} aria-hidden="true" />
              <span className="nav-text">{label}</span>
              {badge === 'review' && reviewCount ? (
                <span className="nav-badge" aria-label={`${reviewCount} awaiting review`}>
                  {reviewCount}
                </span>
              ) : null}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Shell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const { config, parameters, ready, error: configError } = useConfig();
  const overview = useAnalyticsQuery('overview', parameters, { autoStart: ready });
  const reviewCount = num(overview.data?.[0]?.evidence_needs_review);
  const current = nav.find(({ to }) => (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)));

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="Nation Building Authority compliance assurance home">
          <span className="brand-mark" aria-hidden="true">
            NBA
          </span>
          <span className="brand-text">
            <strong>Nation Building Authority</strong>
            <small>Compliance assurance</small>
          </span>
        </Link>
        <NavLinks reviewCount={reviewCount} />
        <p className="sidebar-note">
          All data is synthetic. This workspace supports assurance; it does not interpret regulation.
        </p>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <Sheet open={open} onOpenChange={setOpen}>
            <Button className="mobile-menu" variant="ghost" size="icon" onClick={() => setOpen(true)}>
              <Menu />
              <span className="sr-only">Open navigation</span>
            </Button>
            <SheetContent side="left" className="mobile-sheet" aria-describedby={undefined}>
              <SheetHeader>
                <SheetTitle>Compliance assurance</SheetTitle>
              </SheetHeader>
              <NavLinks onNavigate={() => setOpen(false)} reviewCount={reviewCount} />
            </SheetContent>
          </Sheet>
          <p className="breadcrumbs">
            <span className="crumb-root">Nation Building Authority</span>
            <span aria-hidden="true"> / </span>
            <strong>{current?.label ?? 'Not found'}</strong>
          </p>
          {config?.user && (
            <p className="signed-in" title={`Decisions you record are attributed to ${config.user}`}>
              <span className="sr-only">Signed in as </span>
              {config.user}
            </p>
          )}
        </header>
        <main id="main" tabIndex={-1}>
          {configError ? (
            <div className="page">
              <ErrorState message={configError} />
            </div>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}

function NotFound() {
  useDocumentTitle('Not found');
  return (
    <div className="page">
      <EmptyState title="This page does not exist" action={<Link to="/">Go to the overview</Link>}>
        The link may be out of date.
      </EmptyState>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: (
      <ConfigProvider>
        <Shell />
      </ConfigProvider>
    ),
    children: [
      { path: '/', element: <OverviewPage /> },
      { path: '/obligations', element: <ObligationsPage /> },
      { path: '/evidence', element: <EvidencePage /> },
      { path: '/reports', element: <ReportsPage /> },
      { path: '/audit', element: <AuditPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
