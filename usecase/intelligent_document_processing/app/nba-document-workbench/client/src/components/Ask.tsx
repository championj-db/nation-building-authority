import { GenieChatInput, GenieChatMessageList, useGenieChat } from '@databricks/appkit-ui/react';
import { RotateCcw } from 'lucide-react';
import { Empty } from './primitives';

const EXAMPLES = [
  'Which invoices are due in the next five business days?',
  'Why are invoices being sent back to suppliers?',
  'How ready are we for the 10 business day terms?',
  'Which suppliers have asked to change their bank details?',
];

export function Ask({ enabled, email }: { enabled: boolean; email: string | null }) {
  return (
    <div className="content qa-shell">
      <div className="page-head">
        <div>
          <h1>Ask the AP data</h1>
          <p className="page-intro">
            Answers come from the governed invoice, check and correspondence tables through a Genie space, run as{' '}
            {email ?? 'you'}. Every answer shows the SQL it ran. Extracted bank details are not in scope.
          </p>
        </div>
      </div>
      {enabled ? (
        <Chat />
      ) : (
        <section className="card">
          <Empty title="Ask is not connected">
            The Genie space is created by the pipeline job; bind it to the app to ask questions here.
          </Empty>
        </section>
      )}
    </div>
  );
}

function Chat() {
  const { messages, status, sendMessage, reset, hasPreviousPage, fetchPreviousPage, error } = useGenieChat({
    alias: 'default',
  });
  const busy = status === 'streaming' || status === 'loading-history';
  return (
    <section className="card qa-box" aria-labelledby="ask-title">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'start' }}>
        <h2 id="ask-title">What do you need to know?</h2>
        {messages.length > 0 && (
          <button className="button small" onClick={reset} disabled={busy}>
            <RotateCcw aria-hidden="true" /> New conversation
          </button>
        )}
      </div>
      {messages.length === 0 && (
        <div className="qa-examples" role="group" aria-label="Example questions">
          {EXAMPLES.map((q) => (
            <button key={q} className="filter" onClick={() => sendMessage(q)} disabled={busy}>
              {q}
            </button>
          ))}
        </div>
      )}
      <div className="genie-thread" aria-live="polite">
        {messages.length > 0 && (
          <GenieChatMessageList
            messages={messages}
            status={status}
            hasPreviousPage={hasPreviousPage}
            onFetchPreviousPage={fetchPreviousPage}
          />
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {String(error)}
        </p>
      )}
      <GenieChatInput
        onSend={sendMessage}
        disabled={busy}
        placeholder="Ask about invoices, suppliers, checks or the payment clock"
      />
    </section>
  );
}
