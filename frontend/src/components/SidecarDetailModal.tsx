import { Copy, Pencil, Trash2, Zap } from "lucide-react";
import type { SidecarTemplate } from "../api/types";
import { SidecarDefinitionForm, type SidecarDefinitionFormData } from "./SidecarDefinitionForm";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Tooltip } from "./ui/tooltip";

/** Parse a template's definitionJson into SidecarDefinitionFormData for the form. */
function templateToFormData(template: SidecarTemplate): Partial<SidecarDefinitionFormData> {
  let defn: Record<string, unknown> = {};
  try { defn = JSON.parse(template.definitionJson); } catch { /* ok */ }
  return {
    name: (defn.name as string) ?? template.name,
    description: (defn.description as string) ?? template.description,
    scope: (defn.scope as string) ?? "global",
    phase: (defn.phase as string) ?? "midflight",
    lifetime: (defn.lifetime as string) ?? "ephemeral",
    model: (defn.model as string) ?? "",
    systemPrompt: (defn.systemPrompt as string) ?? "",
    triggers: JSON.stringify(defn.triggers ?? []),
    maxTurns: typeof defn.maxTurns === "number" ? defn.maxTurns : undefined,
    timeoutS: typeof defn.timeoutS === "number" ? defn.timeoutS : undefined,
  };
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

  const formData = templateToFormData(template);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <Zap size={16} className="text-amber-400" />
              {template.name}
            </DialogTitle>
            {onEdit && (
              <Tooltip content="Edit this template">
                <Button size="icon-sm" variant="ghost" onClick={() => onEdit(template)} className="h-7 w-7">
                  <Pencil size={14} />
                </Button>
              </Tooltip>
            )}
          </div>
          <DialogDescription>{template.description}</DialogDescription>
        </DialogHeader>

        <div className="px-5 pb-2">
          <SidecarDefinitionForm
            initial={formData}
            readOnly
            onSave={() => {}}
            onCancel={onClose}
          />

          {/* Metadata */}
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-3 mt-3 border-t border-border">
            <span>Created {new Date(template.createdAt).toLocaleDateString()}</span>
            {template.lastUsedAt && (
              <span>Last used {new Date(template.lastUsedAt).toLocaleDateString()}</span>
            )}
          </div>
        </div>

        {(onDuplicate || onDelete) && (
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
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
