import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { createJob, fetchRepos } from "../api/client";
import { Button } from "../ui/Button";
import { FormField, Label, Select, Textarea, Input } from "../ui/Form";
import { Card, CardContent } from "../ui/Card";
import { VoiceButton } from "./VoiceButton";
import { toast } from "sonner";

export function JobCreationScreen() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<string[]>([]);
  const [repo, setRepo] = useState("");
  const [prompt, setPrompt] = useState("");
  const [baseRef, setBaseRef] = useState("");
  const [branch, setBranch] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchRepos().then((r) => {
      setRepos(r.items);
      setRepo((prev) => prev || r.items[0] || "");
    }).catch(() => toast.error("Failed to load repositories"));
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!repo || !prompt.trim()) return;
    setSubmitting(true);
    try {
      const result = await createJob({
        repo, prompt: prompt.trim(),
        base_ref: baseRef || undefined,
        branch: branch || undefined,
      });
      toast.success(`Job ${result.id} created`);
      navigate(`/jobs/${result.id}`);
    } catch (e) {
      toast.error(`Failed to create job: ${e}`);
    } finally {
      setSubmitting(false);
    }
  }, [repo, prompt, baseRef, branch, navigate]);

  return (
    <div className="max-w-xl mx-auto">
      <h2 className="text-xl font-semibold mb-6">New Job</h2>
      <Card>
        <CardContent>
          <FormField>
            <Label htmlFor="repo">Repository</Label>
            <Select id="repo" value={repo} onChange={(e) => setRepo(e.target.value)}>
              <option value="">Select a repository…</option>
              {repos.map((r) => (
                <option key={r} value={r}>{r.split("/").pop()}</option>
              ))}
            </Select>
          </FormField>

          <FormField>
            <div className="flex items-center justify-between mb-1.5">
              <Label className="mb-0">Prompt</Label>
              <VoiceButton onTranscript={(t) => setPrompt((p) => (p ? p + " " : "") + t)} />
            </div>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the task for the agent…"
            />
          </FormField>

          <button
            className="text-xs text-text-muted flex items-center gap-1 mb-3 cursor-pointer hover:text-text"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "▾" : "▸"} Advanced options
          </button>

          {showAdvanced && (
            <div className="border-t border-border pt-4 space-y-4">
              <FormField>
                <Label>Base Reference</Label>
                <Input value={baseRef} onChange={(e) => setBaseRef(e.target.value)} placeholder="e.g., main" />
              </FormField>
              <FormField>
                <Label>Branch Name</Label>
                <Input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Auto-generated if empty" />
              </FormField>
            </div>
          )}

          <div className="flex gap-3 justify-end mt-6">
            <Button variant="ghost" onClick={() => navigate("/")}>Cancel</Button>
            <Button variant="primary" disabled={submitting || !repo || !prompt.trim()} onClick={handleSubmit}>
              {submitting ? "Creating…" : "Create Job"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
