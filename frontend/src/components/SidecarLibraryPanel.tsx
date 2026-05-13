import { useEffect, useState, useCallback } from "react";
import { Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  fetchSidecarTemplates,
  createSidecarTemplate,
  updateSidecarTemplate,
  deleteSidecarTemplate,
} from "../api/client";
import type { SidecarTemplate } from "../api/types";
import { SidecarDefinitionForm, type SidecarDefinitionFormData } from "./SidecarDefinitionForm";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";
import { ConfirmDialog } from "./ui/confirm-dialog";

export function SidecarLibraryPanel() {
  const [templates, setTemplates] = useState<SidecarTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SidecarTemplate | null>(null);

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
    return <p className="text-sm text-muted-foreground py-2">Loading sidecar templates…</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-foreground">Sidecar Templates</h3>
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          <Plus size={14} />
          New Template
        </Button>
      </div>

      {templates.length === 0 && !creating && (
        <p className="text-sm text-muted-foreground py-4 text-center">
          No saved sidecar templates yet. Create one to reuse across jobs.
        </p>
      )}

      {templates.map((t) => (
        <div
          key={t.id}
          className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2.5"
        >
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
            <p className="text-xs text-muted-foreground truncate">{t.description}</p>
            {t.lastUsedAt && (
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Last used {new Date(t.lastUsedAt).toLocaleDateString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <Button size="icon-sm" variant="ghost" onClick={() => setEditingId(t.id)} title="Edit">
              <Pencil size={14} />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => handleDuplicate(t)} title="Duplicate">
              <Copy size={14} />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => setDeleteTarget(t)} title="Delete" className="text-destructive hover:text-destructive">
              <Trash2 size={14} />
            </Button>
          </div>
        </div>
      ))}

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
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

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
