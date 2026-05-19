import { useEffect, useState, useCallback } from "react";
import { Copy, Pencil, Plus, Trash2, Zap } from "lucide-react";
import { toast } from "sonner";
import {
  fetchSidecarTemplates,
  createSidecarTemplate,
  updateSidecarTemplate,
  deleteSidecarTemplate,
} from "../api/client";
import type { SidecarTemplate } from "../api/types";
import { SidecarDefinitionForm, type SidecarDefinitionFormData } from "./SidecarDefinitionForm";
import { SidecarDetailModal } from "./SidecarDetailModal";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";
import { ConfirmDialog } from "./ui/confirm-dialog";
import { Tooltip } from "./ui/tooltip";

export function SidecarLibraryPanel() {
  const [templates, setTemplates] = useState<SidecarTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SidecarTemplate | null>(null);
  const [viewingTemplate, setViewingTemplate] = useState<SidecarTemplate | null>(null);

  const load = useCallback(() => {
    fetchSidecarTemplates()
      .then((res) => setTemplates(res.items))
      .catch(() => toast.error("Failed to load sidecar templates"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = useCallback(async (_data: SidecarDefinitionFormData, definitionJson: string) => {
    setSaving(true);
    try {
      const parsed = JSON.parse(definitionJson);
      const created = await createSidecarTemplate({
        name: parsed.name,
        description: parsed.description,
        definitionJson,
      });
      setTemplates((prev) => [created, ...prev]);
      setCreating(false);
      toast.success(`Template "${created.name}" created`);
    } catch (e) {
      toast.error(`Failed to create: ${e}`);
    } finally {
      setSaving(false);
    }
  }, []);

  const handleUpdate = useCallback(async (_data: SidecarDefinitionFormData, definitionJson: string) => {
    if (!editingId) return;
    setSaving(true);
    try {
      const parsed = JSON.parse(definitionJson);
      const updated = await updateSidecarTemplate(editingId, {
        name: parsed.name,
        description: parsed.description,
        definitionJson,
      });
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      setEditingId(null);
      toast.success(`Template "${updated.name}" updated`);
    } catch (e) {
      toast.error(`Failed to update: ${e}`);
    } finally {
      setSaving(false);
    }
  }, [editingId]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      await deleteSidecarTemplate(deleteTarget.id);
      setTemplates((prev) => prev.filter((t) => t.id !== deleteTarget.id));
      toast.success(`Deleted "${deleteTarget.name}"`);
    } catch (e) {
      toast.error(`Failed to delete: ${e}`);
    } finally {
      setDeleteTarget(null);
    }
  }, [deleteTarget]);

  const handleDuplicate = useCallback(async (template: SidecarTemplate) => {
    setSaving(true);
    try {
      const defn = JSON.parse(template.definitionJson);
      defn.name = `${defn.name}-copy`;
      const newJson = JSON.stringify(defn);
      const created = await createSidecarTemplate({
        name: `${template.name}-copy`,
        description: template.description,
        definitionJson: newJson,
      });
      setTemplates((prev) => [created, ...prev]);
      toast.success(`Duplicated as "${created.name}"`);
    } catch (e) {
      toast.error(`Failed to duplicate: ${e}`);
    } finally {
      setSaving(false);
    }
  }, []);

  const editingTemplate = editingId ? templates.find((t) => t.id === editingId) : null;
  const editingDefn = editingTemplate ? (() => {
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
        triggers: d.triggers ? JSON.stringify(d.triggers, null, 2) : "[]",
      };
    } catch {
      return undefined;
    }
  })() : undefined;

  if (loading) {
    return <p className="text-sm text-muted-foreground py-4 text-center">Loading sidecar templates…</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-foreground">Sidecar Templates</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Reusable sidecar definitions that can be attached to any job
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          <Plus size={14} />
          New Template
        </Button>
      </div>

      {templates.length === 0 && !creating && (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <div className="rounded-full bg-muted p-3">
            <Zap size={20} className="text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">No saved sidecar templates yet</p>
          <p className="text-xs text-muted-foreground max-w-xs">
            Create a template to define autonomous LLM sessions that run alongside your coding agent — for reviews, gating, monitoring, and more.
          </p>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {templates.map((t) => {
          let defn: Record<string, unknown> = {};
          try { defn = JSON.parse(t.definitionJson); } catch { /* ok */ }
          const phase = (defn.phase as string) ?? "";
          const scopeVal = (defn.scope as string) ?? "global";
          const hasGate = JSON.stringify(defn.triggers ?? []).includes('"gate"');
          const hasAgentMsg = JSON.stringify(defn.triggers ?? []).includes('"agent_message"');

          return (
            <div
              key={t.id}
              className="group flex items-start justify-between gap-3 rounded-lg border border-border px-4 py-3 transition-colors hover:bg-accent/30 cursor-pointer"
              onClick={() => setViewingTemplate(t)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setViewingTemplate(t); }}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Tooltip content={t.name}>
                    <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
                  </Tooltip>
                  {phase && (
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {phase}
                    </Badge>
                  )}
                  {scopeVal !== "global" && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      {scopeVal}
                    </Badge>
                  )}
                  {hasGate && (
                    <Tooltip content="This sidecar can gate (approve/reject) agent actions">
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-600">
                        gate
                      </Badge>
                    </Tooltip>
                  )}
                  {hasAgentMsg && (
                    <Tooltip content="This sidecar can inject messages into the agent's conversation">
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-blue-500/50 text-blue-600">
                        agent message
                      </Badge>
                    </Tooltip>
                  )}
                </div>
                <Tooltip content={t.description}>
                  <p className="text-xs text-muted-foreground mt-0.5 truncate">{t.description}</p>
                </Tooltip>
                {t.lastUsedAt && (
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Last used {new Date(t.lastUsedAt).toLocaleDateString()}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                <Tooltip content="Edit">
                  <Button size="icon-sm" variant="ghost" onClick={() => setEditingId(t.id)}>
                    <Pencil size={14} />
                  </Button>
                </Tooltip>
                <Tooltip content="Duplicate">
                  <Button size="icon-sm" variant="ghost" onClick={() => handleDuplicate(t)}>
                    <Copy size={14} />
                  </Button>
                </Tooltip>
                <Tooltip content="Delete">
                  <Button size="icon-sm" variant="ghost" onClick={() => setDeleteTarget(t)} className="text-destructive hover:text-destructive">
                    <Trash2 size={14} />
                  </Button>
                </Tooltip>
              </div>
            </div>
          );
        })}
      </div>

      {/* Create dialog */}
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New Sidecar Template</DialogTitle>
          </DialogHeader>
          <div className="px-5 pb-5">
            <SidecarDefinitionForm
              onSave={handleCreate}
              onCancel={() => setCreating(false)}
              saving={saving}
              saveLabel="Create Template"
              hideJobScope
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit dialog */}
      <Dialog open={!!editingId} onOpenChange={(open) => { if (!open) setEditingId(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Template</DialogTitle>
          </DialogHeader>
          <div className="px-5 pb-5">
            {editingDefn && (
              <SidecarDefinitionForm
                key={editingId}
                initial={editingDefn}
                onSave={handleUpdate}
                onCancel={() => setEditingId(null)}
                saving={saving}
                saveLabel="Update Template"
                hideJobScope
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* View detail modal */}
      <SidecarDetailModal
        template={viewingTemplate}
        onClose={() => setViewingTemplate(null)}
        onEdit={(t) => { setViewingTemplate(null); setEditingId(t.id); }}
        onDuplicate={(t) => { setViewingTemplate(null); handleDuplicate(t); }}
        onDelete={(t) => { setViewingTemplate(null); setDeleteTarget(t); }}
      />

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title={`Delete "${deleteTarget?.name}"?`}
        description="This template will be permanently removed."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={handleDelete}
      />
    </div>
  );
}
