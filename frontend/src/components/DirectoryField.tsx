import { useCallback, useEffect, useState } from "react";
import { FolderOpen, GitBranch } from "lucide-react";
import { browseDirectories } from "../api/client";
import { Button } from "./ui/button";

interface BrowseEntry {
  name: string;
  path: string;
  isGitRepo: boolean;
}

interface DirectoryFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
}

export function DirectoryField({ label, value, onChange }: DirectoryFieldProps) {
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [browseParent, setBrowseParent] = useState<string | null>(null);
  const [browseCurrent, setBrowseCurrent] = useState("");
  const [browseItems, setBrowseItems] = useState<BrowseEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  const loadBrowse = useCallback(async (path?: string) => {
    setBrowseLoading(true);
    setBrowseError(null);
    try {
      const res = await browseDirectories(path);
      setBrowseCurrent(res.current);
      setBrowseParent(res.parent);
      setBrowseItems(res.items);
      setBrowsePath(res.current);
    } catch (err) {
      setBrowseError(err instanceof Error ? err.message : "Failed to browse directories");
    } finally {
      setBrowseLoading(false);
    }
  }, []);

  useEffect(() => {
    if (browsePath !== null) return;
    void loadBrowse(value || undefined);
  }, [browsePath, loadBrowse, value]);

  return (
    <div className="space-y-2">
      <label className="text-xs text-muted-foreground">{label}</label>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <FolderOpen size={12} />
        <span className="truncate font-mono">{browseCurrent || value || "~"}</span>
      </div>
      {value && <p className="text-[11px] text-muted-foreground">Selected: <span className="font-mono">{value}</span></p>}
      {browseError && (
        <div className="flex items-center justify-between gap-2 text-xs text-red-500">
          <p>{browseError}</p>
          <Button type="button" size="sm" variant="outline" onClick={() => void loadBrowse(browseCurrent || value || undefined)} disabled={browseLoading}>
            Retry
          </Button>
        </div>
      )}
      <div className="max-h-48 overflow-y-auto rounded-md border border-border divide-y divide-border">
        {browseParent !== null && (
          <button
            type="button"
            className="w-full text-left px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/50"
            onClick={() => void loadBrowse(browseParent)}
            disabled={browseLoading}
          >
            .. (parent directory)
          </button>
        )}
        <div className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
          <span className="truncate text-muted-foreground">Current folder</span>
          <Button type="button" size="sm" variant="secondary" onClick={() => onChange(browseCurrent)} disabled={!browseCurrent || browseLoading}>
            Use
          </Button>
        </div>
        {browseLoading ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">Loading...</p>
        ) : browseItems.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">No subdirectories</p>
        ) : (
          browseItems.map((item) => (
            <div key={item.path} className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
              <button
                type="button"
                className="flex-1 min-w-0 text-left truncate hover:text-foreground text-muted-foreground"
                onClick={() => void loadBrowse(item.path)}
              >
                {item.name}
              </button>
              <div className="flex items-center gap-1.5 shrink-0">
                {item.isGitRepo && (
                  <span className="flex items-center gap-1 text-[10px] text-green-500">
                    <GitBranch size={10} /> git
                  </span>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => onChange(item.path)}
                  disabled={value === item.path}
                >
                  {value === item.path ? "Selected" : "Use"}
                </Button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
