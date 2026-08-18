import { useCallback, useEffect, useState } from "react";
import { FolderGit2, FolderOpen, GitBranch, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  browseDirectories,
  createProject,
  createRepo,
  registerRepo,
  unregisterRepo,
} from "../api/client";
import type { ProjectResponse } from "../api/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from "./ui/dialog";

type AddRepoMode = "browse" | "clone" | "init";

interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectResponse) => void;
}

interface BrowseEntry {
  name: string;
  path: string;
  isGitRepo: boolean;
}

export function CreateProjectDialog({ open, onClose, onCreated }: CreateProjectDialogProps) {
  const [name, setName] = useState("");
  const [repoPaths, setRepoPaths] = useState<string[]>([]);
  const [stagedRepoPaths, setStagedRepoPaths] = useState<string[]>([]);
  const [mode, setMode] = useState<AddRepoMode>("browse");

  // Directory browser state
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [browseParent, setBrowseParent] = useState<string | null>(null);
  const [browseCurrent, setBrowseCurrent] = useState("");
  const [browseItems, setBrowseItems] = useState<BrowseEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  // Clone / init inputs
  const [cloneSource, setCloneSource] = useState("");
  const [cloneTo, setCloneTo] = useState("");
  const [initPath, setInitPath] = useState("");
  const [initName, setInitName] = useState("");
  const [addingRepo, setAddingRepo] = useState(false);

  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetState = useCallback(() => {
    setName("");
    setRepoPaths([]);
    setStagedRepoPaths([]);
    setMode("browse");
    setBrowsePath(null);
    setBrowseError(null);
    setCloneSource("");
    setCloneTo("");
    setInitPath("");
    setInitName("");
    setError(null);
  }, []);

  useEffect(() => {
    if (!open) return;
    resetState();
  }, [open, resetState]);

  const loadBrowse = useCallback(async (path?: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const res = await browseDirectories(path);
      setBrowseCurrent(res.current);
      setBrowseParent(res.parent);
      setBrowseItems(res.items);
      setBrowsePath(res.current);
    } catch (err) {
      setBrowseError(err instanceof Error ? err.message : "Failed to browse directories");
    } finally {
      setBrowseLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && mode === "browse" && browsePath === null) {
      void loadBrowse();
    }
  }, [open, mode, browsePath, loadBrowse]);

  function addRepoPath(path: string) {
    const trimmed = path.trim();
    if (!trimmed) return;
    setRepoPaths((items) => (items.includes(trimmed) ? items : [...items, trimmed]));
  }

  async function compensateRegistrations(paths: string[]) {
    const results = await Promise.allSettled(paths.map((path) => unregisterRepo(path)));
    return paths.filter((_, index) => results[index]?.status === "rejected");
  }

  function removeRepoPath(path: string) {
    setRepoPaths((items) => items.filter((item) => item !== path));
    if (stagedRepoPaths.includes(path)) {
      setStagedRepoPaths((items) => items.filter((item) => item !== path));
      void compensateRegistrations([path]).then((failed) => {
        if (failed.length > 0) toast.error(`Could not undo repository registration for ${path}.`);
      });
    }
  }

  const handleAddViaClone = useCallback(async () => {
    if (!cloneSource.trim()) {
      setError("Enter a repository URL or local path to clone/register.");
      return;
    }
    setAddingRepo(true);
    setError(null);
    try {
      const res = await registerRepo(cloneSource.trim(), cloneTo.trim() || undefined);
      addRepoPath(res.path);
      if (res.registered) {
        setStagedRepoPaths((items) => (items.includes(res.path) ? items : [...items, res.path]));
      }
      setCloneSource("");
      setCloneTo("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register repository");
    } finally {
      setAddingRepo(false);
    }
  }, [cloneSource, cloneTo]);

  const handleAddViaInit = useCallback(async () => {
    if (!initPath.trim()) {
      setError("Enter an absolute path for the new repository.");
      return;
    }
    setAddingRepo(true);
    setError(null);
    try {
      const res = await createRepo(initPath.trim(), initName.trim() || undefined);
      addRepoPath(res.path);
      setStagedRepoPaths((items) => (items.includes(res.path) ? items : [...items, res.path]));
      setInitPath("");
      setInitName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create repository");
    } finally {
      setAddingRepo(false);
    }
  }, [initPath, initName]);

  const handleCreate = useCallback(async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Project name is required.");
      return;
    }
    if (repoPaths.length === 0) {
      setError("Add at least one member repository before creating the Project.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const project = await createProject({ name: trimmedName, repoPaths });
      const cleanupFailures = await compensateRegistrations(stagedRepoPaths);
      if (cleanupFailures.length > 0) {
        toast.error(
          `Project saved, but legacy registration remains for: ${cleanupFailures.join(", ")}`,
        );
      }
      setStagedRepoPaths([]);
      onCreated(project);
      onClose();
    } catch (err) {
      const failed = await compensateRegistrations(stagedRepoPaths);
      setStagedRepoPaths([]);
      const reason = err instanceof Error ? err.message : "Failed to create Project";
      const retained = stagedRepoPaths.length > 0
        ? ` Repository files and any completed index remain at: ${stagedRepoPaths.join(", ")}. Remove them manually if unwanted.`
        : "";
      const rollback = failed.length > 0
        ? ` Registration rollback also failed for: ${failed.join(", ")}.`
        : "";
      setError(`${reason}.${retained}${rollback}`);
    } finally {
      setCreating(false);
    }
  }, [name, repoPaths, stagedRepoPaths, onCreated, onClose]);

  const handleClose = useCallback(async () => {
    if (stagedRepoPaths.length > 0) {
      const failed = await compensateRegistrations(stagedRepoPaths);
      if (failed.length > 0) {
        toast.error(`Could not undo repository registration for: ${failed.join(", ")}`);
      }
      toast.info(`Repository files and any completed index remain at: ${stagedRepoPaths.join(", ")}`);
    }
    onClose();
  }, [onClose, stagedRepoPaths]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !creating && !addingRepo && void handleClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderGit2 size={16} className="text-muted-foreground" />
            New Project
          </DialogTitle>
          <DialogDescription>
            Group one or more repositories under a single Project so their board, chats, and
            settings can be managed together.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-5">
          <div className="space-y-1.5">
            <label htmlFor="create-project-name" className="text-xs text-muted-foreground">
              Project name
            </label>
            <Input
              id="create-project-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Payments Platform"
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs text-muted-foreground">Member repositories</label>
              <span className="text-[10px] text-muted-foreground">{repoPaths.length} added</span>
            </div>
            {repoPaths.length === 0 ? (
              <p className="text-xs text-muted-foreground">No repositories added yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {repoPaths.map((path) => (
                  <div
                    key={path}
                    className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-[10px] font-mono"
                  >
                    <span className="truncate max-w-[16rem]">{path}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${path}`}
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => removeRepoPath(path)}
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-lg border border-border bg-background p-3">
            <div className="flex gap-1 rounded-md bg-muted p-0.5 w-fit">
              <button
                type="button"
                className={`px-2.5 py-1 text-xs rounded-sm transition-colors ${mode === "browse" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setMode("browse")}
              >
                Browse existing
              </button>
              <button
                type="button"
                className={`px-2.5 py-1 text-xs rounded-sm transition-colors ${mode === "clone" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setMode("clone")}
              >
                Clone / register
              </button>
              <button
                type="button"
                className={`px-2.5 py-1 text-xs rounded-sm transition-colors ${mode === "init" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setMode("init")}
              >
                Init new
              </button>
            </div>

            {mode === "browse" && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <FolderOpen size={12} />
                  <span className="truncate font-mono">{browseCurrent || "~"}</span>
                </div>
                {browseError && <p className="text-xs text-red-500">{browseError}</p>}
                <div className="max-h-48 overflow-y-auto rounded-md border border-border divide-y divide-border">
                  {browseParent !== null && (
                    <button
                      type="button"
                      className="w-full text-left px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/50"
                      onClick={() => loadBrowse(browseParent)}
                      disabled={browseLoading}
                    >
                      .. (parent directory)
                    </button>
                  )}
                  {browseLoading ? (
                    <p className="px-3 py-2 text-xs text-muted-foreground">Loading…</p>
                  ) : browseItems.length === 0 ? (
                    <p className="px-3 py-2 text-xs text-muted-foreground">No subdirectories</p>
                  ) : (
                    browseItems.map((item) => (
                      <div key={item.path} className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
                        <button
                          type="button"
                          className="flex-1 min-w-0 text-left truncate hover:text-foreground text-muted-foreground"
                          onClick={() => loadBrowse(item.path)}
                        >
                          {item.name}
                        </button>
                        {item.isGitRepo && (
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className="flex items-center gap-1 text-[10px] text-green-500">
                              <GitBranch size={10} /> git
                            </span>
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => addRepoPath(item.path)}
                              disabled={repoPaths.includes(item.path)}
                            >
                              {repoPaths.includes(item.path) ? "Added" : "Add"}
                            </Button>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {mode === "clone" && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  Register an existing local path, or clone a remote URL into a new local directory.
                </p>
                <Input
                  value={cloneSource}
                  onChange={(event) => setCloneSource(event.target.value)}
                  placeholder="Local path or git clone URL"
                />
                <Input
                  value={cloneTo}
                  onChange={(event) => setCloneTo(event.target.value)}
                  placeholder="Clone destination (optional, only for remote URLs)"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleAddViaClone}
                  loading={addingRepo}
                >
                  <Plus size={12} />
                  Register repository
                </Button>
              </div>
            )}

            {mode === "init" && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">
                  Initialize a brand-new git repository at an empty local path.
                </p>
                <Input
                  value={initPath}
                  onChange={(event) => setInitPath(event.target.value)}
                  placeholder="/absolute/path/to/new-repo"
                />
                <Input
                  value={initName}
                  onChange={(event) => setInitName(event.target.value)}
                  placeholder="Repository name (optional)"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleAddViaInit}
                  loading={addingRepo}
                >
                  <Plus size={12} />
                  Create repository
                </Button>
              </div>
            )}
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => void handleClose()} disabled={creating || addingRepo}>
            Cancel
          </Button>
          <Button onClick={handleCreate} loading={creating}>
            Create Project
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
