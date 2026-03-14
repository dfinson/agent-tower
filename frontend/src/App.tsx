import { Routes, Route, NavLink } from "react-router-dom";
import { Component, type ReactNode } from "react";
import { Toaster } from "sonner";
import { useSSE } from "./hooks/useSSE";
import { useTowerStore, selectConnectionStatus } from "./store";
import { DashboardScreen } from "./components/DashboardScreen";
import { JobDetailScreen } from "./components/JobDetailScreen";
import { JobCreationScreen } from "./components/JobCreationScreen";
import { RepositoryDetailView } from "./components/RepositoryDetailView";
import { SettingsScreen } from "./components/SettingsScreen";
import { cn } from "./ui/cn";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="p-8">
          <h2 className="text-error text-lg font-semibold mb-3">Something went wrong</h2>
          <pre className="text-sm text-text-muted whitespace-pre-wrap bg-surface rounded-lg p-4 border border-border overflow-auto">
            {this.state.error.message}{"\n"}{this.state.error.stack}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-4 px-4 py-2 bg-success text-white rounded-md text-sm font-medium hover:bg-success/90 cursor-pointer"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export function App() {
  const connectionStatus = useTowerStore(selectConnectionStatus);
  useSSE();

  return (
    <div className="flex flex-col h-full">
      <Toaster theme="dark" position="top-right" richColors closeButton />

      {connectionStatus !== "connected" && (
        <div className={cn(
          "text-white text-center py-1.5 text-sm flex items-center justify-center gap-2",
          connectionStatus === "disconnected" ? "bg-error" : "bg-warning/80"
        )}>
          {connectionStatus === "disconnected"
            ? "Connection lost — events may be stale"
            : "Connecting…"}
        </div>
      )}

      <header className="flex items-center justify-between px-4 h-12 border-b border-border bg-surface shrink-0">
        <div className="font-semibold text-base">Tower</div>
        <nav className="flex items-center gap-1">
          {[
            { to: "/", label: "Dashboard", end: true },
            { to: "/jobs/new", label: "New Job" },
            { to: "/settings", label: "Settings" },
          ].map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  isActive
                    ? "bg-surface-hover text-text"
                    : "text-text-muted hover:text-text hover:bg-surface-hover"
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              connectionStatus === "connected" && "bg-success",
              connectionStatus === "reconnecting" && "bg-warning animate-pulse",
              connectionStatus === "disconnected" && "bg-error"
            )}
          />
          {connectionStatus}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-4">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<DashboardScreen />} />
            <Route path="/jobs/new" element={<JobCreationScreen />} />
            <Route path="/jobs/:jobId" element={<JobDetailScreen />} />
            <Route path="/repos/:repoPath" element={<RepositoryDetailView />} />
            <Route path="/settings" element={<SettingsScreen />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
