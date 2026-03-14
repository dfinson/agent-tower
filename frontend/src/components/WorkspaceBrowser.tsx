/**
 * WorkspaceBrowser — custom file tree + Monaco code viewer.
 *
 * Simple custom tree per spec — no complex external tree library.
 * Supports expand/collapse, file selection, Monaco preview.
 */
import { useState, useEffect, useCallback } from "react";
import { Paper, Group, Text, UnstyledButton, Loader, ScrollArea } from "@mantine/core";
import { Folder, FolderOpen, FileCode, ChevronRight, ChevronDown } from "lucide-react";
import Editor from "@monaco-editor/react";
import { fetchWorkspaceFiles, fetchWorkspaceFile } from "../api/client";

interface TreeEntry {
  path: string;
  type: "file" | "directory";
  sizeBytes?: number | null;
}

interface TreeNodeProps {
  entry: TreeEntry;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  jobId: string;
}

function TreeNode({ entry, depth, selected, onSelect, jobId }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<TreeEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const isDir = entry.type === "directory";
  const name = entry.path.split("/").pop() ?? entry.path;

  const handleToggle = useCallback(async () => {
    if (!isDir) {
      onSelect(entry.path);
      return;
    }
    if (!expanded && children.length === 0) {
      setLoading(true);
      try {
        const res = await fetchWorkspaceFiles(jobId, { path: entry.path });
        setChildren(res.items);
      } catch { /* */ }
      finally { setLoading(false); }
    }
    setExpanded(!expanded);
  }, [isDir, expanded, children.length, entry.path, jobId, onSelect]);

  return (
    <>
      <UnstyledButton
        onClick={handleToggle}
        className={`flex items-center gap-1.5 py-1 px-2 rounded text-sm w-full transition-colors ${
          selected === entry.path
            ? "bg-[var(--mantine-color-dark-5)]"
            : "hover:bg-[var(--mantine-color-dark-6)]"
        }`}
        style={{ paddingLeft: depth * 16 + 8 }}
      >
        {isDir ? (
          expanded ? <ChevronDown size={14} className="shrink-0" /> : <ChevronRight size={14} className="shrink-0" />
        ) : (
          <span className="w-3.5" />
        )}
        {isDir ? (
          expanded ? <FolderOpen size={14} className="text-yellow-500 shrink-0" /> : <Folder size={14} className="text-yellow-500 shrink-0" />
        ) : (
          <FileCode size={14} className="text-[var(--mantine-color-dimmed)] shrink-0" />
        )}
        <Text size="xs" truncate>{name}</Text>
        {loading && <Loader size={10} />}
      </UnstyledButton>
      {expanded && children.map((c) => (
        <TreeNode key={c.path} entry={c} depth={depth + 1} selected={selected} onSelect={onSelect} jobId={jobId} />
      ))}
    </>
  );
}

function guessLang(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const m: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", json: "json",
    yaml: "yaml", yml: "yaml", md: "markdown", html: "html", css: "css",
    sh: "shell", sql: "sql", toml: "toml", rb: "ruby", php: "php",
  };
  return m[ext] ?? "plaintext";
}

interface Props { jobId: string; }

export default function WorkspaceBrowser({ jobId }: Props) {
  const [entries, setEntries] = useState<TreeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);

  useEffect(() => {
    fetchWorkspaceFiles(jobId)
      .then((res) => setEntries(res.items))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [jobId]);

  const handleSelect = useCallback(async (path: string) => {
    setSelected(path);
    setFileLoading(true);
    try {
      const res = await fetchWorkspaceFile(jobId, path);
      setFileContent(res.content);
    } catch {
      setFileContent("// Failed to load file");
    } finally {
      setFileLoading(false);
    }
  }, [jobId]);

  if (loading) return <div className="flex justify-center py-10"><Loader /></div>;

  return (
    <div className="flex gap-3 h-[500px]">
      <Paper radius="lg" p={0} className="w-64 shrink-0 flex flex-col overflow-hidden">
        <Group className="px-3 py-2.5 border-b border-[var(--mantine-color-dark-4)]">
          <Text size="xs" fw={600} c="dimmed">Files</Text>
        </Group>
        <ScrollArea className="flex-1">
          <div className="py-1">
            {entries.map((e) => (
              <TreeNode key={e.path} entry={e} depth={0} selected={selected} onSelect={handleSelect} jobId={jobId} />
            ))}
          </div>
        </ScrollArea>
      </Paper>

      <Paper radius="lg" p={0} className="flex-1 overflow-hidden">
        {fileLoading ? (
          <div className="flex items-center justify-center h-full"><Loader /></div>
        ) : selected && fileContent != null ? (
          <Editor
            value={fileContent}
            language={guessLang(selected)}
            theme="vs-dark"
            options={{ readOnly: true, minimap: { enabled: false }, scrollBeyondLastLine: false, fontSize: 13 }}
          />
        ) : (
          <Text size="sm" c="dimmed" ta="center" py="xl">Select a file to preview</Text>
        )}
      </Paper>
    </div>
  );
}
