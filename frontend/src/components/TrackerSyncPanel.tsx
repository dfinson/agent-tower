import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  fetchCredentials,
  fetchProjects,
  fetchTrackerLinks,
  refreshTrackerLink,
} from "../api/client";
import type { Credential } from "../api/client";
import type {
  ProjectResponse,
  TrackerLinkResponse,
  TrackerSummaryResponse,
} from "../api/types";
import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";

interface ProjectLinks {
  project: ProjectResponse;
  links: TrackerLinkResponse[];
}

export function TrackerSyncPanel() {
  const [groups, setGroups] = useState<ProjectLinks[]>([]);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [projectsResponse, credentialsResponse] = await Promise.all([
        fetchProjects(),
        fetchCredentials(),
      ]);
      const links = await Promise.all(
        projectsResponse.items.map(async (project) => ({
          project,
          links: (await fetchTrackerLinks(project.id)).trackerLinks ?? [],
        })),
      );
      setGroups(links);
      setCredentials(credentialsResponse.credentials);
    } catch (error) {
      toast.error(String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const credentialById = useMemo(
    () => new Map(credentials.map((credential) => [credential.id, credential])),
    [credentials],
  );

  const updateSummary = (
    projectId: string,
    linkId: string,
    summary: TrackerSummaryResponse,
  ) => {
    setGroups((current) =>
      current.map((group) =>
        group.project.id !== projectId
          ? group
          : {
              ...group,
              links: group.links.map((link) =>
                link.id === linkId ? { ...link, summary } : link,
              ),
            },
      ),
    );
  };

  const handleRefresh = async (projectId: string, link: TrackerLinkResponse) => {
    setRefreshing(link.id);
    try {
      const summary = await refreshTrackerLink(projectId, link.id);
      updateSummary(projectId, link.id, summary);
      toast.success(`Refreshed ${link.externalRef}.`);
    } catch (error) {
      toast.error(String(error));
      await load();
    } finally {
      setRefreshing(null);
    }
  };

  const linkedGroups = groups.filter((group) => group.links.length > 0);

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div>
        <p className="text-sm font-semibold">Synced tracker state</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          Ticket state is fetched by polling or with a manual refresh. CodePlane does not expose tracker webhooks.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-4"><Spinner /></div>
      ) : linkedGroups.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tracker links attached yet.</p>
      ) : (
        <div className="space-y-4">
          {linkedGroups.map(({ project, links }) => (
            <section key={project.id} className="space-y-2">
              <h4 className="text-sm font-medium">{project.name}</h4>
              {links.map((link) => {
                const credential = credentialById.get(link.credentialId);
                const summary = link.summary;
                return (
                  <div key={link.id} className="rounded-md border border-border p-3 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-medium">
                          {credential?.label ?? "Unknown credential"}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          <span>{credential?.provider.replace("_", " ") ?? "unknown"}</span>
                          {" · "}
                          <span>{link.externalRef}</span>
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          {summary?.lastSyncedAt
                            ? `Last synced ${new Date(summary.lastSyncedAt).toLocaleString()}`
                            : "Never synced"}
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Refresh ${link.externalRef}`}
                        disabled={refreshing === link.id}
                        onClick={() => void handleRefresh(project.id, link)}
                      >
                        <RefreshCw className={`h-3.5 w-3.5 ${refreshing === link.id ? "animate-spin" : ""}`} />
                        Refresh
                      </Button>
                    </div>

                    {summary?.lastError && (
                      <p role="alert" className="text-xs text-red-400">{summary.lastError}</p>
                    )}

                    {!summary || !summary.tickets?.length ? (
                      <p className="text-xs text-muted-foreground">No tickets fetched.</p>
                    ) : (
                      <div className="space-y-1">
                        {summary.tickets.map((ticket) => {
                          const content = (
                            <>
                              <span className="font-medium">{ticket.title}</span>
                              <span className="text-muted-foreground">{ticket.status}</span>
                            </>
                          );
                          return ticket.url ? (
                            <a
                              key={ticket.id}
                              href={ticket.url}
                              target="_blank"
                              rel="noreferrer"
                              className="flex justify-between gap-3 rounded px-2 py-1 text-xs hover:bg-accent"
                            >
                              {content}
                            </a>
                          ) : (
                            <div key={ticket.id} className="flex justify-between gap-3 rounded px-2 py-1 text-xs">
                              {content}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
