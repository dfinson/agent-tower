import { useEffect, useState, useCallback } from "react";
import { ChevronDown, ChevronRight, Info, Plus, Zap } from "lucide-react";
import { toast } from "sonner";
import { fetchSidecarTemplates, createSidecarTemplate, updateSidecarTemplate } from "../api/client";
import type { SidecarTemplate } from "../api/types";
import { SidecarDefinitionForm, type SidecarDefinitionFormData } from "./SidecarDefinitionForm";
import { SidecarDetailModal } from "./SidecarDetailModal";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";
import { Tooltip } from "./ui/tooltip";

interface SidecarPickerProps {
  /** Currently selected template IDs */
  selected: string[];
  /** Called when the selection changes */
  onSelectionChange: (ids: string[]) => void;
  /** Called when inline definitions are created (not saved to library yet) */
  onInlineDefinitions: (definitions: string[]) => void;
  inlineDefinitions: string[];
}

export function SidecarPicker({
  selected,
  onSelectionChange,
  onInlineDefinitions,
  inlineDefinitions,
}: SidecarPickerProps) {
  const [templates, setTemplates] = useState<SidecarTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [expandedInline, setExpandedInline] = useState<number | null>(null);
  const [viewingTemplate, setViewingTemplate] = useState<SidecarTemplate | null>(null);
  const [editingTemplate, setEditingTemplate] = useState<SidecarTemplate | null>(null);

  useEffect(() => {
    fetchSidecarTemplates()
      .then((res) => setTemplates(res.items))
      .catch(() => toast.error("Failed to load sidecar templates"))
      .finally(() => setLoading(false));
  }, []);

  const toggleTemplate = useCallback((id: string) => {
    onSelectionChange(
      selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id],
    );
  }, [selected, onSelectionChange]);

  const handleInlineCreate = useCallback(async (_data: SidecarDefinitionFormData, definitionJson: string) => {
    setSaving(true);
    try {
      // Save to library and auto-select
      const parsed = JSON.parse(definitionJson);
      const created = await createSidecarTemplate({
        name: parsed.name,
        description: parsed.description,
        definitionJson,
      });
      setTemplates((prev) => [created, ...prev]);
      onSelectionChange([...selected, created.id]);
      setCreating(false);
      toast.success(`Template "${created.name}" created and attached`);
    } catch (e) {
      // If library save fails, still attach as inline
      onInlineDefinitions([...inlineDefinitions, definitionJson]);
      setCreating(false);
      toast.info("Attached as inline sidecar (not saved to library)");
    } finally {
      setSaving(false);
    }
  }, [selected, onSelectionChange, onInlineDefinitions, inlineDefinitions]);

  const removeInline = useCallback((index: number) => {
    onInlineDefinitions(inlineDefinitions.filter((_, i) => i !== index));
  }, [inlineDefinitions, onInlineDefinitions]);

  const handleEditSave = useCallback(async (_data: SidecarDefinitionFormData, definitionJson: string) => {
    if (!editingTemplate) return;
    setSaving(true);
    try {
      const parsed = JSON.parse(definitionJson);
      const updated = await updateSidecarTemplate(editingTemplate.id, {
        name: parsed.name,
        description: parsed.description,
        definitionJson,
      });
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      setEditingTemplate(null);
      toast.success(`Template "${updated.name}" updated`);
    } catch (e) {
      toast.error(`Failed to update: ${e}`);
    } finally {
      setSaving(false);
    }
  }, [editingTemplate]);

  if (loading) {
    return <p className="text-xs text-muted-foreground py-1">Loading templates…</p>;
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Tooltip content="Autonomous LLM sessions that run alongside the agent — for reviews, gating, monitoring, or injecting feedback">
            <span className="text-xs font-medium text-foreground cursor-help flex items-center gap-1">
              <Zap size={12} className="text-muted-foreground" />
              Sidecars
            </span>
          </Tooltip>
          {selected.length > 0 && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{selected.length}</Badge>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={() => setCreating(true)} className="h-7 text-xs">
          <Plus size={12} />
          New
        </Button>
      </div>

      {templates.length === 0 && inlineDefinitions.length === 0 && (
        <p className="text-xs text-muted-foreground py-1">
          No saved templates. Create one to attach a sidecar to this job.
        </p>
      )}

      {/* Saved templates with checkboxes */}
      {templates.map((t) => {
        let defn: Record<string, unknown> = {};
        try { defn = JSON.parse(t.definitionJson); } catch { /* ok */ }
        const phase = (defn.phase as string) ?? "";
        const hasGate = JSON.stringify(defn.triggers ?? []).includes('"gate"');
        const hasAgentMsg = JSON.stringify(defn.triggers ?? []).includes('"agent_message"');

        return (
          <label
            key={t.id}
            className="flex items-start gap-2.5 rounded-lg border border-border px-3 py-2.5 cursor-pointer hover:bg-accent/40 transition-colors"
          >
            <input
              type="checkbox"
              checked={selected.includes(t.id)}
              onChange={() => toggleTemplate(t.id)}
              className="mt-0.5 accent-primary"
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap">
                <Tooltip content={t.name}>
                  <span className="text-xs font-medium text-foreground truncate">{t.name}</span>
                </Tooltip>
                {phase && (
                  <Badge variant="secondary" className="text-[9px] px-1 py-0">{phase}</Badge>
                )}
                {hasGate && (
                  <Tooltip content="This sidecar can gate (approve/reject) agent actions">
                    <Badge variant="outline" className="text-[9px] px-1 py-0 border-amber-500/50 text-amber-600">gate</Badge>
                  </Tooltip>
                )}
                {hasAgentMsg && (
                  <Tooltip content="This sidecar can inject messages into the agent's conversation">
                    <Badge variant="outline" className="text-[9px] px-1 py-0 border-blue-500/50 text-blue-600">msg</Badge>
                  </Tooltip>
                )}
              </div>
              <Tooltip content={t.description}>
                <p className="text-[11px] text-muted-foreground truncate mt-0.5">{t.description}</p>
              </Tooltip>
            </div>
            <Tooltip content="View details">
              <button
                type="button"
                className="shrink-0 mt-0.5 p-0.5 rounded text-muted-foreground hover:text-foreground transition-colors"
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setViewingTemplate(t); }}
              >
                <Info size={14} />
              </button>
            </Tooltip>
          </label>
        );
      })}

      {/* Inline definitions (created in this session, not yet saved) */}
      {inlineDefinitions.map((defJson, i) => {
        let parsed: { name?: string; description?: string } = {};
        try {
          parsed = JSON.parse(defJson);
        } catch {
          parsed = { name: `Inline sidecar ${i + 1} (corrupted)`, description: "Failed to parse definition" };
        }
        return (
          <div key={i} className="rounded border border-dashed border-border px-2.5 py-2">
            <div className="flex items-center justify-between">
              <button
                type="button"
                className="flex items-center gap-1 text-xs font-medium text-foreground"
                onClick={() => setExpandedInline(expandedInline === i ? null : i)}
              >
                {expandedInline === i ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                {parsed.name || `Inline sidecar ${i + 1}`}
              </button>
              <Button size="icon-sm" variant="ghost" onClick={() => removeInline(i)} className="h-5 w-5 text-muted-foreground">
                ×
              </Button>
            </div>
            {parsed.description && <p className="text-[11px] text-muted-foreground truncate">{parsed.description}</p>}
            {expandedInline === i && (
              <pre className="mt-2 text-[10px] font-mono text-muted-foreground bg-muted/50 rounded p-2 overflow-x-auto max-h-40 overflow-y-auto">
                {JSON.stringify(parsed, null, 2)}
              </pre>
            )}
          </div>
        );
      })}

      {/* Inline creation dialog */}
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Sidecar</DialogTitle>
          </DialogHeader>
          <div className="px-5 pb-5">
            <SidecarDefinitionForm
              onSave={handleInlineCreate}
              onCancel={() => setCreating(false)}
              saving={saving}
              saveLabel="Add to Job"
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* View detail modal */}
      <SidecarDetailModal
        template={viewingTemplate}
        onClose={() => setViewingTemplate(null)}
        onEdit={(t) => { setViewingTemplate(null); setEditingTemplate(t); }}
      />

      {/* Edit modal */}
      <Dialog open={!!editingTemplate} onOpenChange={(open) => { if (!open) setEditingTemplate(null); }}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Sidecar</DialogTitle>
          </DialogHeader>
          <div className="px-5 pb-5">
            {editingTemplate && (
              <SidecarDefinitionForm
                key={editingTemplate.id}
                initial={(() => {
                  try {
                    const d = JSON.parse(editingTemplate.definitionJson);
                    return {
                      name: d.name ?? editingTemplate.name,
                      description: d.description ?? editingTemplate.description,
                      scope: d.scope ?? "global",
                      phase: d.phase ?? "postflight",
                      lifetime: d.lifetime ?? "ephemeral",
                      model: d.model ?? "",
                      systemPrompt: d.systemPrompt ?? "",
                      triggers: JSON.stringify(d.triggers ?? []),
                      maxTurns: typeof d.maxTurns === "number" ? d.maxTurns : undefined,
                      timeoutS: typeof d.timeoutS === "number" ? d.timeoutS : undefined,
                    };
                  } catch { return undefined; }
                })()}
                onSave={handleEditSave}
                onCancel={() => setEditingTemplate(null)}
                saving={saving}
                saveLabel="Save Changes"
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
