import { useEffect, useState, useCallback } from "react";
import { Trash2, Plus, Wrench } from "lucide-react";
import { toast } from "sonner";
import {
  fetchGlobalConfig, updateGlobalConfig,
  fetchRepos, unregisterRepo,
  cleanupWorktrees,
} from "../api/client";
import { AddRepoModal } from "./AddRepoModal";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Spinner } from "./ui/spinner";

export function SettingsScreen() {
  const [loading, setLoading] = useState(true);
  const [repos, setRepos] = useState<string[]>([]);
  const [configYaml, setConfigYaml] = useState("");
  const [savedYaml, setSavedYaml] = useState("");
  const [addRepoOpen, setAddRepoOpen] = useState(false);

  useEffect(() => {
    Promise.all([fetchGlobalConfig(), fetchRepos()])
      .then(([configRes, reposRes]) => {
        setConfigYaml(configRes.config_yaml);
        setSavedYaml(configRes.config_yaml);
        setRepos(reposRes.items);
      })
      .catch(() => toast.error("Failed to load settings"))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveConfig = useCallback(async () => {
    try {
      const res = await updateGlobalConfig(configYaml);
      setSavedYaml(res.config_yaml);
      toast.success("Config saved");
    } catch (e) {
      toast.error(String(e));
    }
  }, [configYaml]);

  const handleRepoAdded = useCallback((path: string) => {
    setRepos((prev) => (prev.includes(path) ? prev : [...prev, path]));
  }, []);

  const handleRemoveRepo = useCallback(async (path: string) => {
    try {
      await unregisterRepo(path);
      setRepos((prev) => prev.filter((r) => r !== path));
      toast.success("Repository removed");
    } catch (e) {
      toast.error(String(e));
    }
  }, []);

  const handleCleanup = useCallback(async () => {
    try {
      await cleanupWorktrees();
      toast.success("Worktrees cleaned up");
    } catch (e) {
      toast.error(String(e));
    }
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-5">
      <h3 className="text-lg font-semibold">Settings</h3>

      {/* Repositories */}
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-semibold">Repositories ({repos.length})</span>
          <Button size="sm" onClick={() => setAddRepoOpen(true)}>
            <Plus size={14} />
            Add Repository
          </Button>
        </div>

        <AddRepoModal
          opened={addRepoOpen}
          onClose={() => setAddRepoOpen(false)}
          onAdded={handleRepoAdded}
        />

        {repos.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">No repositories registered</p>
        ) : (
          <div className="flex flex-col gap-1">
            {repos.map((r) => (
              <div
                key={r}
                className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-accent group"
              >
                <span className="text-sm font-mono text-muted-foreground truncate flex-1" title={r}>{r}</span>
                <button
                  type="button"
                  onClick={() => handleRemoveRepo(r)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-red-400 hover:text-red-300 hover:bg-red-400/10"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Global Config */}
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-3">Global Configuration</p>
        <Textarea
          value={configYaml}
          onChange={(e) => setConfigYaml(e.currentTarget.value)}
          className="font-mono text-xs"
          rows={12}
        />
        <div className="flex justify-end gap-2 mt-3">
          <Button
            variant="ghost"
            size="sm"
            disabled={configYaml === savedYaml}
            onClick={() => setConfigYaml(savedYaml)}
          >
            Reset
          </Button>
          <Button
            size="sm"
            disabled={configYaml === savedYaml}
            onClick={handleSaveConfig}
          >
            Save Config
          </Button>
        </div>
      </div>

      {/* Maintenance */}
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-3">Maintenance</p>
        <Button variant="outline" size="sm" onClick={handleCleanup}>
          <Wrench size={14} />
          Clean Up Worktrees
        </Button>
      </div>
    </div>
  );
}
