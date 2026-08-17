import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Settings, GitBranch, Globe, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  fetchProject,
  fetchRepoDetail,
  fetchTrackerLinks,
  fetchCredentials,
  createTrackerLink,
  updateProject,
} from "../api/client";
import type { Credential } from "../api/client";
import type { ProjectResponse, RepoDetailResponse, TrackerLinkResponse } from "../api/types";
import { RepoIndexIndicator } from "./RepoIndexIndicator";
import { Spinner } from "./ui/spinner";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export function RepoSettings() {
  const { projectId } = useParams<{ projectId: string }>();

  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<RepoDetailResponse | null>(null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [projectName, setProjectName] = useState("");
  const [repoPaths, setRepoPaths] = useState<string[]>([]);
  const [trackerLinks, setTrackerLinks] = useState<TrackerLinkResponse[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [selectedCredentialId, setSelectedCredentialId] = useState("");
  const [externalRef, setExternalRef] = useState("");
  const [newRepoPath, setNewRepoPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [attachingTracker, setAttachingTracker] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const [proj, credentialsResp] = await Promise.all([
        fetchProject(projectId),
        fetchCredentials(),
      ]);
      const nextCredentials = credentialsResp.credentials ?? [];
      setCredentials(nextCredentials);
      setSelectedCredentialId((current) => current || nextCredentials[0]?.id || "");
      setProject(proj);
      setProjectName(proj.name);
      setRepoPaths(proj.repoPaths);
      const primaryRepo = proj.repoPaths[0];
      if (primaryRepo) {
        setDetail(await fetchRepoDetail(primaryRepo));
      } else {
        setDetail(null);
      }
      const trackerResp = await fetchTrackerLinks(proj.id);
      setTrackerLinks(trackerResp.trackerLinks ?? []);
    } catch {
      toast.error("Failed to load Project details");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const saveProject = useCallback(async () => {
    if (!project) return;
    setSaving(true);
    try {
      const trimmedName = projectName.trim();
      const uniquePaths = [...new Set(repoPaths.filter((path) => path.trim()))].map((path) => path.trim());
      const updated = await updateProject(project.id, {
        name: trimmedName || project.name,
        repoPaths: uniquePaths,
      });
      setProject(updated);
      setProjectName(updated.name);
      setRepoPaths(updated.repoPaths);
      toast.success("Project updated");
    } catch (error) {
      toast.error(String(error));
    } finally {
      setSaving(false);
    }
  }, [project, projectName, repoPaths]);

  const credentialMap = Object.fromEntries(credentials.map((credential) => [credential.id, credential]));

  const attachTrackerLink = useCallback(async () => {
    if (!project || !selectedCredentialId.trim() || !externalRef.trim()) {
      toast.error("Choose a credential and enter a board or project reference.");
      return;
    }
    setAttachingTracker(true);
    try {
      await createTrackerLink(project.id, {
        credentialId: selectedCredentialId,
        externalRef: externalRef.trim(),
      });
      setExternalRef("");
      const trackerResp = await fetchTrackerLinks(project.id);
      setTrackerLinks(trackerResp.trackerLinks ?? []);
      toast.success("Board link attached");
    } catch (error) {
      toast.error(String(error));
    } finally {
      setAttachingTracker(false);
    }
  }, [externalRef, project, selectedCredentialId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link
          to={`/projects/id/${encodeURIComponent(projectId ?? "")}`}
          className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Back to overview"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Settings size={16} className="text-muted-foreground" />
            Project Settings
          </h1>
          <p className="text-sm text-muted-foreground truncate">{project?.name ?? ""}</p>
        </div>
      </div>

      {!project ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground">
          Project details unavailable
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">Project configuration</h3>
              <Button size="sm" onClick={saveProject} loading={saving}>Save project</Button>
            </div>

            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Project name</label>
              <Input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project name" />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs text-muted-foreground">Member repositories</label>
                <span className="text-[10px] text-muted-foreground">{repoPaths.length} total</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {repoPaths.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No member repositories yet.</p>
                ) : repoPaths.map((path) => (
                  <div key={path} className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-[10px] font-mono">
                    <span className="truncate max-w-[16rem]">{path}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${path}`}
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => setRepoPaths((items) => items.filter((item) => item !== path))}
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex gap-2 pt-1">
                <Input
                  value={newRepoPath}
                  onChange={(event) => setNewRepoPath(event.target.value)}
                  placeholder="/absolute/path/to/repo"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    const trimmed = newRepoPath.trim();
                    if (!trimmed) return;
                    setRepoPaths((items) => [...new Set([...items, trimmed])]);
                    setNewRepoPath("");
                  }}
                >
                  <Plus size={12} />
                  Add
                </Button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">Integrations & board sync</h3>
              <Link to="/settings" className="text-xs text-primary hover:underline">Manage integrations</Link>
            </div>

            {credentials.length === 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">No board or org integrations attached to this Project yet.</p>
                <p className="text-xs text-muted-foreground">
                  Register credentials in Settings → Integrations, then attach their board/project refs here.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]">
                  <select
                    value={selectedCredentialId}
                    onChange={(event) => setSelectedCredentialId(event.target.value)}
                    className="h-9 rounded-md border border-border bg-background px-2 text-xs text-foreground"
                    aria-label="Select tracker credential"
                  >
                    {credentials.map((credential) => (
                      <option key={credential.id} value={credential.id}>
                        {credential.label}
                      </option>
                    ))}
                  </select>
                  <Input
                    value={externalRef}
                    onChange={(event) => setExternalRef(event.target.value)}
                    placeholder="ORG/project or board ref"
                    aria-label="Board or org ref"
                  />
                  <Button onClick={attachTrackerLink} loading={attachingTracker} className="whitespace-nowrap">
                    <Plus size={12} />
                    Attach
                  </Button>
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Example: <span className="font-mono">acme/project-board</span> or <span className="font-mono">PROJ-42</span>
                </div>
              </div>
            )}

            {trackerLinks.length === 0 ? (
              <p className="text-xs text-muted-foreground">No linked boards or org refs yet.</p>
            ) : (
              <div className="space-y-2">
                {trackerLinks.map((link) => (
                  <div key={link.id} className="rounded-md border border-border bg-background px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-medium">{link.externalRef}</p>
                      <span className="text-[10px] text-muted-foreground">
                        {credentialMap[link.credentialId]?.label ?? link.credentialId}
                      </span>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      {link.summary?.lastSyncedAt ? `Last synced ${new Date(link.summary.lastSyncedAt).toLocaleString()}` : "Awaiting sync"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {detail && (
            <div className="rounded-lg border border-border bg-card p-5 space-y-4">
              <h3 className="text-sm font-semibold">Repository Information</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Path</p>
                  <p className="font-mono text-xs text-foreground break-all">{detail.path}</p>
                </div>
                {detail.originUrl && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                      <Globe size={10} /> Origin URL
                    </p>
                    <p className="font-mono text-xs text-foreground break-all">{detail.originUrl}</p>
                  </div>
                )}
                {detail.baseBranch && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                      <GitBranch size={10} /> Default Branch
                    </p>
                    <p className="text-foreground">{detail.baseBranch}</p>
                  </div>
                )}
                {detail.currentBranch && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                      <GitBranch size={10} /> Current Branch
                    </p>
                    <p className="text-foreground">{detail.currentBranch}</p>
                  </div>
                )}
                {detail.platform && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Platform</p>
                    <p className="text-foreground capitalize">{detail.platform}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {project.repoPaths[0] && (
            <div className="rounded-lg border border-border bg-card p-5 space-y-3">
              <h3 className="text-sm font-semibold">Index Status</h3>
              <div className="flex items-center gap-3">
                <RepoIndexIndicator repo={project.repoPaths[0]} />
                <span className="text-sm text-muted-foreground">
                  {detail?.activeJobCount ?? 0} active jobs using this repository
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
