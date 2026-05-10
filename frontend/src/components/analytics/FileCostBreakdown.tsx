import { FileCode } from "lucide-react";
import { type FileCostResponse } from "../../api/client-analytics";
import { formatUsd } from "./helpers";

/**
 * File-centric cost breakdown (Item 14).
 * Stacked bar chart showing most expensive files with read/write split.
 */

interface Props {
  data: FileCostResponse | null;
}

export function FileCostBreakdown({ data }: Props) {
  if (!data?.files?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <FileCode size={14} />
          File Cost
        </div>
        <p className="text-muted-foreground text-sm mt-2">No file cost data yet.</p>
      </div>
    );
  }

  const maxCost = Math.max(...data.files.map((f) => f.totalCostUsd));

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <FileCode size={14} />
        Most Expensive Files
      </div>

      <div className="space-y-2 max-h-80 overflow-y-auto">
        {data.files.map((file) => {
          const readPct = file.totalCostUsd > 0 ? (file.totalReadCost / file.totalCostUsd) * 100 : 0;
          const writePct = 100 - readPct;
          const barWidth = maxCost > 0 ? (file.totalCostUsd / maxCost) * 100 : 0;

          return (
            <div key={file.filePath} className="space-y-0.5">
              <div className="flex justify-between text-xs">
                <span className="text-foreground truncate max-w-[70%]" title={file.filePath}>
                  {file.filePath.split("/").slice(-2).join("/")}
                </span>
                <span className="text-muted-foreground">
                  {formatUsd(file.totalCostUsd)}
                  <span className="ml-1 text-[10px]">({file.totalTurns} turns, {file.jobCount} jobs)</span>
                </span>
              </div>
              <div className="flex h-2 rounded overflow-hidden" style={{ width: `${barWidth}%` }}>
                {readPct > 0 && (
                  <div
                    className="bg-blue-500"
                    style={{ width: `${readPct}%` }}
                    title={`Read: ${formatUsd(file.totalReadCost)}`}
                  />
                )}
                {writePct > 0 && (
                  <div
                    className="bg-green-500"
                    style={{ width: `${writePct}%` }}
                    title={`Write: ${formatUsd(file.totalWriteCost)}`}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex gap-4 text-[10px] text-muted-foreground pt-1 border-t border-border">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded bg-blue-500" /> Read cost
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded bg-green-500" /> Write cost
        </span>
      </div>
    </div>
  );
}
