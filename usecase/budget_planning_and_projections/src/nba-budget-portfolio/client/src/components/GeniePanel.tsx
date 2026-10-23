import { GenieChatInput, GenieChatMessageList, useGenieChat } from '@databricks/appkit-ui/react';
import { RotateCcw, Scale, X } from 'lucide-react';
import type { PageId } from '../App';

const STARTERS: Record<PageId, string[]> = {
  overview: [
    'Which programs grew most against the endorsed plan over FY27–31, and why?',
    'How much of the FY29 forecast can the market not deliver, and which input binds?',
    'Which projects have the lowest forecast confidence and what drives it?',
  ],
  scenarios: [
    'Compare Capacity balanced with the Working baseline: which projects move and by how much?',
    'Which regional projects finish later in the Capacity balanced scenario?',
    'What does Accelerated delivery do to capacity breaches by year?',
  ],
  capacity: [
    'Which projects drive the FY29 skilled civil labour breach in the working baseline?',
    'Which delivery inputs are constrained in each year of the horizon?',
    'Which deferrable projects use the most electrical equipment in FY30?',
  ],
  variance: [
    'Which projects have the largest unexplained variance this financial year?',
    'Break down the current-year variance by driver for Eastern Transit Corridor.',
    'Which programs are outside tolerance over the horizon?',
  ],
  cycle: [
    'Which programs have not submitted this month’s forecast?',
    'Summarise the commentary recorded against Western Freight Link.',
    'Which programs moved most since the endorsed plan?',
  ],
  assurance: [
    'Which assumptions are awaiting attestation and when are they due for review?',
    'Which programs have a Gateway rating of Amber/Red or worse?',
    'What delay cost rate does the forecast assume?',
  ],
  briefing: [
    'What are the three biggest risks to deliverability over FY27–31?',
    'How does the forecast compare with the funding envelope each year?',
    'Which forecast run produced the current figures, and on what actuals date?',
  ],
};

export function GeniePanel({ open, page, email, onClose }: { open: boolean; page: PageId; email?: string | null; onClose: () => void }) {
  const { messages, status, sendMessage, reset, hasPreviousPage, fetchPreviousPage, error } = useGenieChat({ alias: 'default' });
  const busy = !['idle', 'error'].includes(String(status));
  return (
    <aside className={`assistant ${open ? 'open' : ''}`} aria-label="Portfolio data assistant" aria-hidden={!open}>
      <div className="assistant-head">
        <div><strong>Portfolio Genie</strong><div className="kpi-label">Asking as {email ?? 'you'}</div></div>
        <div className="actions">
          {messages.length > 0 && <button className="button icon-button" aria-label="New conversation" onClick={reset}><RotateCcw size={16} /></button>}
          <button className="button icon-button" aria-label="Close assistant" onClick={onClose}><X size={18} /></button>
        </div>
      </div>
      <div className="assistant-governance"><Scale size={15} /><span>Answers are generated SQL over the governed portfolio tables, run with your Unity Catalog permissions. Expand the SQL to check how each figure was produced.</span></div>
      <div className="assistant-chat">
        {messages.length === 0 ? (
          <div className="starters">
            <p className="kpi-label">Suggested for this page</p>
            {STARTERS[page].map((q) => <button key={q} className="starter" onClick={() => sendMessage(q)} disabled={busy}>{q}</button>)}
          </div>
        ) : (
          <GenieChatMessageList className="genie-list" messages={messages} status={status} hasPreviousPage={hasPreviousPage} onFetchPreviousPage={fetchPreviousPage} />
        )}
        {error && <p className="assistant-error">{error}</p>}
      </div>
      <div className="assistant-input"><GenieChatInput onSend={sendMessage} disabled={busy} placeholder="Ask about the portfolio…" /></div>
      <p className="assistant-disclaimer">AI-generated from synthetic working figures. Verify against the SQL and the source tables before relying on an answer.</p>
    </aside>
  );
}
