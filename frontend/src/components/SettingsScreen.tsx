import { useEffect, useState, useCallback } from "react";
import {
  fetchGlobalConfig,
  updateGlobalConfig,
  fetchRepos,
  registerRepo,
  unregisterRepo,
  cleanupWorktrees,
} from "../api/client";
import { Card, CardHeader, CardTitle, CardContent } from "../ui/Card";
import { Button } from "../ui/Button";
import { Input, Textarea } from "../ui/Form";
import { Spinner, EmptyState } from "../ui/Feedback";
import { toast } from "sonner";

export function SettingsScreen() {
  const [loading, setLoading] = useState(true);
  const [repos, setRepos] = useState<string[]>([]);
  const [configYaml, setConfigYaml] = useState("");
  const [savedYaml, setSavedYaml] = useState("");
  const [newRepo, setNewRepo] = useState("");

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
    } catch (e) { toast.error(`Save failed: ${e}`); }
  }, [configYaml]);

  const handleAddRepo = useCallback(async () => {
    if (!newRepo.trim()) return;
    try {
      await registerRepo(newRepo.trim());
      setNewRepo("");
      const res = await fetchRepos();
      setRepos(res.items);
      toast.success("Repository added");
    } catch (e) { toast.error(`Add failed: ${e}`); }
  }, [newRepo]);

  const handleRemoveRepo = useCallback(async (path: string) => {
    try {
      await unregisterRepo(path);
      setRepos((prev) => prev.filter((r) => r !== path));
      toast.success("Repository removed");
    } catch (e) { toast.error(`Remove failed: ${e}`); }
  }, []);

  const handleCleanup = useCallback(async () => {
    try {
      await cleanupWorktrees();
      toast.success("Worktrees cleaned up");
    } catch (e) { toast.error(`Cleanup failed: ${e}`); }
  }, []);

  if (loading) return <Spinner />;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h2 className="text-xl font-semibold">Settings</h2>

      {/* Repos */}
      <Card>
        <CardHeader>
          <CardTitle>Repositories ({repos.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 mb-4">
            <Input
              value={newRepo}
              onChange={(e) => setNewRepo(e.target.value)}
              placeholder="Local path or git URL"
              onKeyDown={(e) => e.key === "Enter" && handleAddRepo()}
            />
            <Button size="sm" onClick={handleAddRepo} disabled={!newRepo.trim()}>Add</Button>
          </div>
          {repos.length === 0 ? (
            <EmptyState text="No repositories registered" />
          ) : (
            <div className="space-y-1">
              {repos.map((r) => (
                <div key={r} className="flex items-center justify-between py-2 px-3 rounded hover:bg-surface-hover group">
                  <span className="text-sm font-mono text-text-muted truncate" title={r}>{r}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="opacity-0 group-hover:opacity-100 text-error"
                    onClick={() => handleRemoveRepo(r)}
                  >
                    Remove
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Global Config */}
      <Card>
        <CardHeader>
          <CardTitle>Global Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea
            value={configYaml}
            onChange={(e) => setConfigYaml(e.target.value)}
            className="font-mono text-xs min-h-[300px]"
          />
          <div className="flex gap-2 justify-end mt-3">
            <Button
              variant="ghost"
              size="sm"
              disabled={configYaml === savedYaml}
              onClick={() => setConfigYaml(savedYaml)}
            >
              Reset
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={configYaml === savedYaml}
              onClick={handleSaveConfig}
            >
              Save Config
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Maintenance</CardTitle>
        </CardHeader>
        <CardContent>
          <Button size="sm" onClick={handleCleanup}>
            Clean Up Worktrees
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
