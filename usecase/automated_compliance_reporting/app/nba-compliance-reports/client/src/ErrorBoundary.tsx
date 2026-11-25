import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Last-resort boundary: a plain message and a way out, with technical detail tucked away. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fatal-error" role="alert">
        <h1>Something went wrong on this screen</h1>
        <p>No decisions were lost: anything you recorded before this is already saved. Reload to continue.</p>
        <div className="inline-actions">
          <button type="button" className="fatal-button" onClick={() => window.location.reload()}>
            Reload
          </button>
          <a href="/">Go to the overview</a>
        </div>
        <details>
          <summary>Technical detail</summary>
          <pre>{this.state.error.stack ?? String(this.state.error)}</pre>
        </details>
      </div>
    );
  }
}
