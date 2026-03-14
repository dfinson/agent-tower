/**
 * AddRepoModal — shared component for adding repositories.
 *
 * Supports three modes:
 * 1. Paste local path
 * 2. Paste git URL
 * 3. Browse server filesystem
 */
import { useState, useCallback, useEffect } from "react";
import {
  Modal, TextInput, Button, Group, Stack, Text, Tabs, Paper,
  UnstyledButton, Loader, ScrollArea,
} from "@mantine/core";
import { Folder, FolderOpen, GitBranch, ArrowUp, Link, HardDrive } from "lucide-react";
import { notifications } from "@mantine/notifications";
import { registerRepo, browseDirectories } from "../api/client";

interface AddRepoModalProps {
  opened: boolean;
  onClose: () => void;
  onAdded: (path: string) => void;
}

export function AddRepoModal({ opened, onClose, onAdded }: AddRepoModalProps) {
  const [tab, setTab] = useState<string | null>("path");
  const [input, setInput] = useState("");
  const [adding, setAdding] = useState(false);

  // Browser state
  const [browsePath, setBrowsePath] = useState("~");
  const [browseEntries, setBrowseEntries] = useState<{ name: string; path: string; isGitRepo: string }[]>([]);
  const [browseParent, setBrowseParent] = useState<string | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);

  const handleAdd = useCallback(async (source: string) => {
    if (!source.trim()) return;
    setAdding(true);
    try {
      const result = await registerRepo(source.trim());
      notifications.show({ color: "green", message: `Added: ${result.path.split("/").pop()}` });
      onAdded(result.path);
      setInput("");
      onClose();
    } catch (e) {
      notifications.show({ color: "red", title: "Failed to add", message: String(e) });
    } finally {
      setAdding(false);
    }
  }, [onAdded, onClose]);

  const loadDirectory = useCallback(async (path: string) => {
    setBrowseLoading(true);
    try {
      const result = await browseDirectories(path);
      setBrowsePath(result.current);
      setBrowseParent(result.parent);
      setBrowseEntries(result.items);
    } catch {
      notifications.show({ color: "red", message: "Failed to browse directory" });
    } finally {
      setBrowseLoading(false);
    }
  }, []);

  // Load initial directory when browse tab opens
  useEffect(() => {
    if (tab === "browse" && browseEntries.length === 0) {
      loadDirectory("~");
    }
  }, [tab, browseEntries.length, loadDirectory]);

  return (
    <Modal opened={opened} onClose={onClose} title="Add Repository" size="md" centered>
      <Tabs value={tab} onChange={setTab}>
        <Tabs.List mb="md">
          <Tabs.Tab value="path" leftSection={<HardDrive size={14} />}>Local Path</Tabs.Tab>
          <Tabs.Tab value="url" leftSection={<Link size={14} />}>Git URL</Tabs.Tab>
          <Tabs.Tab value="browse" leftSection={<Folder size={14} />}>Browse</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="path">
          <Stack gap="sm">
            <TextInput
              placeholder="/home/user/projects/my-repo"
              value={input}
              onChange={(e) => setInput(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd(input)}
              size="sm"
            />
            <Group justify="flex-end">
              <Button size="sm" loading={adding} disabled={!input.trim()} onClick={() => handleAdd(input)}>
                Add Repository
              </Button>
            </Group>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="url">
          <Stack gap="sm">
            <TextInput
              placeholder="https://github.com/user/repo.git"
              value={input}
              onChange={(e) => setInput(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd(input)}
              size="sm"
            />
            <Text size="xs" c="dimmed">The repository will be cloned to the server.</Text>
            <Group justify="flex-end">
              <Button size="sm" loading={adding} disabled={!input.trim()} onClick={() => handleAdd(input)}>
                Clone & Add
              </Button>
            </Group>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="browse">
          <Paper bg="dark.8" radius="md" p="xs" mb="sm">
            <Group gap="xs">
              {browseParent && (
                <UnstyledButton onClick={() => loadDirectory(browseParent)} className="p-1 rounded hover:bg-[var(--mantine-color-dark-6)]">
                  <ArrowUp size={14} />
                </UnstyledButton>
              )}
              <Text size="xs" ff="monospace" c="dimmed" truncate className="flex-1">{browsePath}</Text>
            </Group>
          </Paper>

          <ScrollArea h={250}>
            {browseLoading ? (
              <div className="flex justify-center py-8"><Loader size="sm" /></div>
            ) : browseEntries.length === 0 ? (
              <Text size="sm" c="dimmed" ta="center" py="md">No subdirectories</Text>
            ) : (
              <Stack gap={2}>
                {browseEntries.map((entry) => {
                  const isGit = entry.isGitRepo === "true";
                  return (
                    <Group
                      key={entry.path}
                      justify="space-between"
                      className="px-2 py-1.5 rounded hover:bg-[var(--mantine-color-dark-6)] cursor-pointer"
                      onClick={() => isGit ? handleAdd(entry.path) : loadDirectory(entry.path)}
                    >
                      <Group gap="xs">
                        {isGit ? (
                          <GitBranch size={14} className="text-green-500" />
                        ) : (
                          <FolderOpen size={14} className="text-yellow-500" />
                        )}
                        <Text size="sm">{entry.name}</Text>
                      </Group>
                      {isGit && (
                        <Text size="xs" c="green">git repo — click to add</Text>
                      )}
                    </Group>
                  );
                })}
              </Stack>
            )}
          </ScrollArea>
        </Tabs.Panel>
      </Tabs>
    </Modal>
  );
}
