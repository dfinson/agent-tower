import { useEffect, useState, useCallback } from "react";
import { Outlet, useParams, useNavigate, Link } from "react-router-dom";
import { FolderGit2, Plus, ChevronLeft, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { fetchRepos } from "../api/client";
import { useStore } from "../store";
import { cn } from "../lib/utils";
import { Spinner } from "./ui/spinner";
import { Button } from "./ui/button";
import { pathBasename } from "../lib/paths";
import { matchesNameFilter } from "../lib/nameFilter";
import { ProjectsOverview } from "./ProjectsOverview";


export function RepoLayout() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const navigate = useNavigate();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";
  const [repos, setRepos] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const repoIndexState = useStore((s) => s.repoIndexState);

  const loadRepos = useCallback(async () => {
    try {
      const res = await fetchRepos();
      setRepos(res.items);
    } catch {
      toast.error("Failed to load repositories");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRepos(); }, [loadRepos]);

  function repoBasename(path: string) {
    return pathBasename(path) || path;
  }

  function isActive(path: string) {
    return decoded === path;
  }

  const filteredRepos = repos.filter((r) => matchesNameFilter(repoBasename(r), filterQuery));

  return (
    <div className="flex h-full min-h-0">
      {/* Sidebar */}
      <aside
        className={cn(
          "shrink-0 border-r border-border bg-card flex flex-col transition-all duration-200",
          collapsed ? "w-12" : "w-56",
        )}
      >
        <div className="flex items-center justify-between px-3 py-3 border-b border-border">
          {!collapsed && (
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Repos
            </span>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto py-1" aria-label="Repository list">
          {!collapsed && !loading && repos.length > 0 && (
            <div className="px-2 pb-2">
              <input
                type="text"
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
                placeholder="Filter..."
                aria-label="Filter repositories by name"
                className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          )}
          {loading ? (
            <div className="flex justify-center py-4">
              <Spinner className="w-4 h-4" />
            </div>
          ) : repos.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4 px-2">
              No repositories
            </p>
          ) : filteredRepos.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4 px-2">
              No matches
            </p>
          ) : (
            filteredRepos.map((r) => {
              const name = repoBasename(r);
              const indexing = repoIndexState[r];
              return (
                <Link
                  key={r}
                  to={`/repos/${encodeURIComponent(r)}`}
                  title={r}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 text-sm transition-colors",
                    isActive(r)
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  )}
                >
                  <FolderGit2 size={14} className="shrink-0" />
                  {!collapsed && (
                    <>
                      <span className="flex-1 truncate">{name}</span>
                      {indexing && (
                        <span className="text-[10px] text-blue-400 shrink-0">indexing</span>
                      )}
                    </>
                  )}
                </Link>
              );
            })
          )}
        </nav>

        {!collapsed && (
          <div className="border-t border-border p-2">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-xs"
              onClick={() => navigate("/settings")}
            >
              <Plus size={12} />
              Add repo
            </Button>
          </div>
        )}
      </aside>

      {/* Main content area */}
      <div className="flex-1 min-w-0 overflow-y-auto p-4 md:p-6">
        {!repoPath ? <ProjectsOverview /> : <Outlet />}
      </div>
    </div>
  );
}
