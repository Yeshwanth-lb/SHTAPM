// One page failing to render must not blank the whole application (D052):
// the shell, navigation and every other page stay usable, and the operator is
// told which page failed.
import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class PageBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="state state--error" role="alert" data-testid="page-error">
          <p className="state__title">This page could not be displayed</p>
          <p className="state__body">
            The rest of the system is unaffected. Open another page from the menu, or reload.
            <br />
            <span className="mono t-muted">{this.state.error.message}</span>
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
