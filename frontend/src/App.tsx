import { Component, type ReactNode, useState } from "react";
import { Routes, Route, NavLink, Link } from "react-router-dom";
import { type LucideIcon, LayoutDashboard, Plus, Settings, Menu } from "lucide-react";
import { useSSE } from "./hooks/useSSE";
import { useTowerStore, selectConnectionStatus } from "./store";
import { DashboardScreen } from "./components/DashboardScreen";
import { JobDetailScreen } from "./components/JobDetailScreen";
import { JobCreationScreen } from "./components/JobCreationScreen";
import { SettingsScreen } from "./components/SettingsScreen";
import { DotBadge } from "./components/ui/badge";
import { Sheet } from "./components/ui/sheet";

/* ------------------------------------------------------------------ */
/* Error boundary                                                      */
/* ------------------------------------------------------------------ */

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-8 max-w-2xl mx-auto">
          <p className="text-lg font-semibold text-red-400 mb-2">Something went wrong</p>
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap bg-card rounded-lg p-4 border border-border overflow-auto">
            {this.state.error.message}{"\n"}{this.state.error.stack}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/* ------------------------------------------------------------------ */
/* Nav item                                                            */
/* ------------------------------------------------------------------ */

function NavItem({
  to,
  icon: Icon,
  label,
  end,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors no-underline ${
          isActive
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:text-foreground hover:bg-accent"
        }`
      }
    >
      <Icon size={16} />
      <span className="hidden sm:inline">{label}</span>
    </NavLink>
  );
}

/* ------------------------------------------------------------------ */
/* Connection status                                                   */
/* ------------------------------------------------------------------ */

function ConnectionStatus() {
  const status = useTowerStore(selectConnectionStatus);
  const color = status === "connected" ? "green" : status === "reconnecting" ? "yellow" : "red";
  return (
    <DotBadge color={color}>
      {status === "reconnecting" ? "connecting" : status}
    </DotBadge>
  );
}

/* ------------------------------------------------------------------ */
/* App                                                                 */
/* ------------------------------------------------------------------ */

export function App() {
  useSSE();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex flex-col h-screen">
      <header className="flex items-center justify-between px-4 h-12 shrink-0 border-b border-border bg-card">
        <Link to="/" className="no-underline">
          <span className="font-bold text-sm text-foreground tracking-tight cursor-pointer hover:opacity-80">
            Tower
          </span>
        </Link>

        <div className="hidden sm:flex items-center gap-1">
          <NavItem to="/" icon={LayoutDashboard} label="Dashboard" end />
          <NavItem to="/jobs/new" icon={Plus} label="New Job" />
          <NavItem to="/settings" icon={Settings} label="Settings" />
        </div>

        <div className="flex items-center gap-2">
          <ConnectionStatus />
          <button
            className="sm:hidden p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            onClick={() => setMenuOpen(true)}
          >
            <Menu size={20} />
          </button>
        </div>
      </header>

      <Sheet open={menuOpen} onClose={() => setMenuOpen(false)} title="Tower">
        <div className="flex flex-col gap-1">
          {[
            { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
            { to: "/jobs/new", icon: Plus, label: "New Job" },
            { to: "/settings", icon: Settings, label: "Settings" },
          ].map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium no-underline ${
                  isActive
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
          <div className="border-t border-border mt-2 pt-3 px-1">
            <ConnectionStatus />
          </div>
        </div>
      </Sheet>

      <main className="flex-1 overflow-y-auto p-4">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<DashboardScreen />} />
            <Route path="/jobs/new" element={<JobCreationScreen />} />
            <Route path="/jobs/:jobId" element={<JobDetailScreen />} />
            <Route path="/settings" element={<SettingsScreen />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
