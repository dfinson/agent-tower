import { FilePlus, Pencil } from "lucide-react";
import { useMemo } from "react";
import type { Step } from "../store";
import { useStore, selectStepEntries } from "../store";

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

function parentDir(path: string): string {
  const parts = path.split("/");
  if (parts.length <= 1) return "";
  return parts[parts.length - 2] ?? "";
}

/** Tools that create new files. */
const CREATE_TOOLS = new Set(["create_file", "Write", "write", "write_file"]);

export function FilesTouchedChips({ step }: { step: Step }) {
  const stepEntries = useStore(selectStepEntries(step.jobId, step.stepId));

  // Detect which files were created (vs edited) from tool_call entries
  const createdFiles = useMemo(() => {
    const created = new Set<string>();
    for (const e of stepEntries) {
      if (e.role !== "tool_call" || !e.toolName) continue;
      const name = e.toolName.split("/").pop() ?? e.toolName;
      if (!CREATE_TOOLS.has(name)) continue;
      if (!e.toolArgs) continue;
      try {
        const args = JSON.parse(e.toolArgs);
        const fp = args.filePath ?? args.file_path ?? args.path ?? "";
        if (fp) created.add(fp);
      } catch { /* skip */ }
    }
    return created;
  }, [stepEntries]);

  if (!step.filesWritten?.length) return null;

  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {step.filesWritten.map((f) => {
        const isCreate = createdFiles.has(f);
        const dir = parentDir(f);
        return (
          <span
            key={f}
            title={f}
            className={
              isCreate
                ? "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-500/10 text-blue-600"
                : "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-600"
            }
          >
            {isCreate ? <FilePlus size={10} /> : <Pencil size={10} />}
            {basename(f)}
            {dir && <span className="text-[10px] opacity-60">{dir}/</span>}
          </span>
        );
      })}
    </div>
  );
}
