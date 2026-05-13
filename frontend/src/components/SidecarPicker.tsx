import { useEffect, useState, useCallback } from "react";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { toast } from "sonner";
import { fetchSidecarTemplates, createSidecarTemplate } from "../api/client";
import type { SidecarTemplate } from "../api/types";
import { SidecarDefinitionForm, type SidecarDefinitionFormData } from "./SidecarDefinitionForm";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";

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

  if (loading) {
    return <p className="text-xs text-muted-foreground">Loading templates…</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-foreground">Sidecars</p>
        <Button size="sm" variant="ghost" onClick={() => setCreating(true)} className="h-7 text-xs">
          <Plus size={12} />
          New
        </Button>
      </div>

      {templates.length === 0 && inlineDefinitions.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No saved templates. Create one to attach a sidecar to this job.
        </p>
      )}

      {/* Saved templates with checkboxes */}
      {templates.map((t) => (
        <label
          key={t.id}
          className="flex items-start gap-2 rounded border border-border px-2.5 py-2 cursor-pointer hover:bg-accent/50 transition-colors"
        >
          <input
            type="checkbox"
            checked={selected.includes(t.id)}
            onChange={() => toggleTemplate(t.id)}
            className="mt-0.5 accent-primary"
          />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-foreground truncate">{t.name}</p>
            <p className="text-[11px] text-muted-foreground truncate">{t.description}</p>
          </div>
        </label>
      ))}

      {/* Inline definitions (created in this session, not yet saved) */}
      {inlineDefinitions.map((defJson, i) => {
        let parsed: { name?: string; description?: string } = {};
        try { parsed = JSON.parse(defJson); } catch { /* ignore */ }
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
    </div>
  );
}
