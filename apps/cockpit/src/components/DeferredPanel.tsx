import { Component, Suspense, type ReactNode } from 'react';

type Props = { label: string; children: ReactNode; fallback?: ReactNode };

export class DeferredPanel extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() { return { failed: true }; }

  render() {
    if (this.state.failed) return <>{this.props.fallback}<div className="notice" role="alert">
      <p>{this.props.label} could not load. Reload the cockpit to try again.</p>
      <button onClick={() => window.location.reload()}>Reload cockpit</button>
    </div></>;
    return <Suspense fallback={this.props.fallback ?? <p className="permission-note" role="status">
      Loading {this.props.label}…
    </p>}>{this.props.children}</Suspense>;
  }
}
