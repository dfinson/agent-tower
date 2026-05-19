import { Copy, Pencil, Trash2, Zap } from "lucide-react";
import type { SidecarTemplate } from "../api/types";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";

const PHASE_LABELS: Record<string, string> = {
  preflight: "Preflight — runs before the agent starts",
  midflight: "Midflight — runs while the agent is working",
  postflight: "Postflight — runs after the agent finishes",
};

const LIFETIME_LABELS: Record<string, string> = {
  ephemeral: "Ephemeral — fires once then closes",
  windowed: "Windowed — active for a limited duration or turn count",
  persistent: "Persistent — stays active for the entire job",
};

const SCOPE_LABELS: Record<string, string> = {
  global: "Global — applies to all jobs",
  repo: "Repository — applies to jobs in a specific repo",
  job: "Job — attached to individual jobs",
};

function conditionSummary(trigger: Record<string, unknown>): string {
  const cond = trigger.condition as Record<string, unknown> | undefined;
  if (!cond) return "manual";
  const kind = cond.kind as string;
  if (kind === "timer") return `Every ${cond.intervalS ?? cond.interval_s ?? "?"}s`;
  if (kind === "event") return `On event: ${cond.eventKind ?? (cond.eventKinds as string[] | undefined)?.join(", ") ?? "?"}`;
  if (kind === "threshold") return `After ${cond.value ?? "?"} ${cond.metric ?? "messages"}`;
  if (kind === "regex") return `Regex: ${cond.pattern ?? "?"}`;
  if (kind === "file_pattern") return `File: ${cond.glob ?? "?"}`;
  if (kind === "content_match") return `Keywords: ${(cond.keywords as string[] | undefined)?.join(", ") ?? "?"}`;
  if (kind === "manual") return "Manual trigger";
  return kind;
}

export function SidecarDetailModal({
  template,
  onClose,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  template: SidecarTemplate | null;
  onClose: () => void;
  onEdit?: (t: SidecarTemplate) => void;
  onDuplicate?: (t: SidecarTemplate) => void;
  onDelete?: (t: SidecarTemplate) => void;
}) {
  if (!template) return null;

  let defn: Record<string, unknown> = {};
  try { defn = JSON.parse(template.definitionJson); } catch { /* ok */ }

  const phase = (defn.phase as string) ?? "midflight";
  const lifetime = (defn.lifetime as string) ?? "ephemeral";
  const scope = (defn.scope as string) ?? "global";
  const model = (defn.model as string) ?? "";
  const systemPrompt = (defn.systemPrompt as string) ?? "";
  const triggers = (defn.triggers as Record<string, unknown>[]) ?? [];
  const toolAccess = (defn.toolAccess as string) ?? "none";

  const hasActions = onEdit || onDuplicate || onDelete;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Zap size={16} className="text-amber-400" />
            {template.name}
          </DialogTitle>
          <DialogDescription>{template.description}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 px-5 pb-2 text-sm">
          {/* Phase / Lifetime / Scope */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <span className="text-muted-foreground">Phase</span>
              <p className="font-medium">{PHASE_LABELS[phase] ?? phase}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Lifetime</span>
              <p className="font-medium">{LIFETIME_LABELS[lifetime] ?? lifetime}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Scope</span>
              <p className="font-medium">{SCOPE_LABELS[scope] ?? scope}</p>
            </div>
            {model && (
              <div>
                <span className="text-muted-foreground">Model</span>
                <p className="font-medium">{model}</p>
              </div>
            )}
            {toolAccess !== "none" && (
              <div>
                <span className="text-muted-foreground">Tool Access</span>
                <p className="font-medium">{toolAccess}</p>
              </div>
            )}
          </div>

          {/* Triggers */}
          {triggers.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">Triggers</span>
              <ul className="mt-1 flex flex-col gap-1">
                {triggers.map((t, i) => (
                  <li key={i} className="text-xs bg-muted/40 rounded px-2 py-1.5 font-mono">
                    {conditionSummary(t)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* System prompt preview */}
          {systemPrompt && (
            <div>
              <span className="text-xs text-muted-foreground">System Prompt</span>
              <pre className="mt-1 text-xs bg-muted/40 rounded px-2 py-1.5 max-h-32 overflow-y-auto whitespace-pre-wrap break-words">
                {systemPrompt}
              </pre>
            </div>
          )}

          {/* Metadata */}
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-1 border-t border-border">
            <span>Created {new Date(template.createdAt).toLocaleDateString()}</span>
            {template.lastUsedAt && (
              <span>Last used {new Date(template.lastUsedAt).toLocaleDateString()}</span>
            )}
          </div>
        </div>

        {hasActions && (
          <DialogFooter className="px-5 pb-5 flex items-center gap-2">
            {onDuplicate && (
              <Button size="sm" variant="outline" onClick={() => onDuplicate(template)}>
                <Copy size={14} />
                Duplicate
              </Button>
            )}
            {onDelete && (
              <Button size="sm" variant="outline" className="text-destructive hover:text-destructive" onClick={() => onDelete(template)}>
                <Trash2 size={14} />
                Delete
              </Button>
            )}
            <div className="flex-1" />
            {onEdit && (
              <Button size="sm" onClick={() => onEdit(template)}>
                <Pencil size={14} />
                Edit
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
