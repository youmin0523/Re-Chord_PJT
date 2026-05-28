import { Component } from "react";
import { Bug, RotateCcw } from "lucide-react";
import i18n from "@/i18n";

// Class component → use the imperative i18n.t instead of the hook.
const t = (k) => i18n.t(k);

/** Top-level error boundary so a single component crash doesn't blank the app. */
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary] caught:", error, info);
  }
  reset = () => this.setState({ error: null });
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-md w-full glass rounded-2xl p-6 space-y-4 glow-magenta">
          <div className="flex items-center gap-2">
            <Bug className="size-5 text-magenta" />
            <span className="text-sm font-semibold">{t("boundary.title")}</span>
          </div>
          <pre className="mono text-[11px] text-fg-muted whitespace-pre-wrap break-words rounded-lg bg-black/40 p-3 max-h-48 overflow-auto">
            {String(this.state.error?.message || this.state.error)}
          </pre>
          <div className="flex items-center gap-2">
            <button
              onClick={this.reset}
              className="inline-flex items-center gap-1.5 rounded-full h-9 px-4 text-xs font-medium bg-gradient-to-br from-violet to-magenta text-white"
            >
              <RotateCcw className="size-3.5" /> {t("errors.card_retry")}
            </button>
            <a
              href="/"
              className="text-xs text-fg-muted hover:text-fg"
            >
              {t("boundary.reload")}
            </a>
          </div>
        </div>
      </div>
    );
  }
}
