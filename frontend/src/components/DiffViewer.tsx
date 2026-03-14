/**
 * DiffViewer — Monaco-based diff viewing per spec.
 *
 * Uses Monaco DiffEditor for the primary diff experience.
 * File list sidebar shows changed files with status indicators.
 */
import { useState, useEffect } from "react";
import { Paper, Group, Text, Stack, UnstyledButton, Badge, Loader } from "@mantine/core";
import { type LucideIcon, FileCode, FilePlus, FileMinus, FileEdit } from "lucide-react";
import { DiffEditor } from "@monaco-editor/react";
import { useTowerStore } from "../store";

interface DiffViewerProps {
  jobId: string;
}

const STATUS_ICON: Record<string, LucideIcon> = {
  added: FilePlus,
  deleted: FileMinus,
  modified: FileEdit,
  renamed: FileEdit,
};

const STATUS_COLOR: Record<string, string> = {
  added: "green",
  deleted: "red",
  modified: "blue",
  renamed: "yellow",
};

function guessLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", kt: "kotlin",
    rb: "ruby", php: "php", cs: "csharp", cpp: "cpp", c: "c", h: "c",
    json: "json", yaml: "yaml", yml: "yaml", toml: "toml",
    md: "markdown", html: "html", css: "css", scss: "scss",
    sql: "sql", sh: "shell", bash: "shell", dockerfile: "dockerfile",
  };
  return map[ext] ?? "plaintext";
}

export default function DiffViewer({ jobId }: DiffViewerProps) {
  const diffs = useTowerStore((s) => s.diffs[jobId] ?? []);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [original, setOriginal] = useState("");
  const [modified, setModified] = useState("");
  const [loading, setLoading] = useState(false);

  const selectedFile = diffs[selectedIdx];

  // Build modified content from hunks
  useEffect(() => {
    if (!selectedFile) return;
    setLoading(true);

    // Build content from hunks for the diff display
    const additions = selectedFile.hunks
      ?.flatMap((h: { lines?: { type: string; content: string }[] }) =>
        (h.lines ?? []).filter((l: { type: string }) => l.type !== "deletion").map((l: { content: string }) => l.content)
      )
      .join("\n") ?? "";

    const deletions = selectedFile.hunks
      ?.flatMap((h: { lines?: { type: string; content: string }[] }) =>
        (h.lines ?? []).filter((l: { type: string }) => l.type !== "addition").map((l: { content: string }) => l.content)
      )
      .join("\n") ?? "";

    setOriginal(deletions);
    setModified(additions);
    setLoading(false);
  }, [selectedFile]);

  const totalAdditions = diffs.reduce((sum, f) => sum + (f.additions ?? 0), 0);
  const totalDeletions = diffs.reduce((sum, f) => sum + (f.deletions ?? 0), 0);

  if (diffs.length === 0) {
    return (
      <Paper radius="lg" p="xl">
        <Text size="sm" c="dimmed" ta="center">No changes detected</Text>
      </Paper>
    );
  }

  return (
    <div className="flex gap-3 h-[500px]">
      {/* File list sidebar */}
      <Paper radius="lg" p={0} className="w-64 shrink-0 flex flex-col overflow-hidden">
        <Group justify="space-between" className="px-3 py-2.5 border-b border-[var(--mantine-color-dark-4)]">
          <Text size="xs" fw={600} c="dimmed">{diffs.length} files</Text>
          <Group gap={4}>
            <Text size="xs" c="green">+{totalAdditions}</Text>
            <Text size="xs" c="red">-{totalDeletions}</Text>
          </Group>
        </Group>
        <Stack gap={0} className="flex-1 overflow-y-auto">
          {diffs.map((file, i) => {
            const Icon = STATUS_ICON[file.status] ?? FileCode;
            return (
              <UnstyledButton
                key={i}
                onClick={() => setSelectedIdx(i)}
                className={`flex items-center gap-2 px-3 py-2 text-sm transition-colors ${
                  i === selectedIdx
                    ? "bg-[var(--mantine-color-dark-5)]"
                    : "hover:bg-[var(--mantine-color-dark-6)]"
                }`}
              >
                <Icon size={14} className={`text-[var(--mantine-color-${STATUS_COLOR[file.status]}-5)] shrink-0`} />
                <Text size="xs" truncate className="flex-1">{file.path}</Text>
                <Badge size="xs" variant="light" color={STATUS_COLOR[file.status]}>
                  +{file.additions} -{file.deletions}
                </Badge>
              </UnstyledButton>
            );
          })}
        </Stack>
      </Paper>

      {/* Monaco Diff Editor */}
      <Paper radius="lg" p={0} className="flex-1 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader />
          </div>
        ) : selectedFile ? (
          <DiffEditor
            original={original}
            modified={modified}
            language={guessLanguage(selectedFile.path)}
            theme="vs-dark"
            options={{
              readOnly: true,
              minimap: { enabled: false },
              renderSideBySide: true,
              scrollBeyondLastLine: false,
              fontSize: 13,
            }}
          />
        ) : null}
      </Paper>
    </div>
  );
}
