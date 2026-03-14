import { useEffect, useState, useCallback } from "react";
import {
  Paper, Title, TextInput, Textarea, Button, Group, Stack, Text, Loader, ActionIcon,
} from "@mantine/core";
import { Trash2, Plus, Wrench } from "lucide-react";
import { notifications } from "@mantine/notifications";
import {
  fetchGlobalConfig, updateGlobalConfig,
  fetchRepos, registerRepo, unregisterRepo,
  cleanupWorktrees,
} from "../api/client";

export function SettingsScreen() {
  const [loading, setLoading] = useState(true);
  const [repos, setRepos] = useState<string[]>([]);
  const [configYaml, setConfigYaml] = useState("");
  const [savedYaml, setSavedYaml] = useState("");
  const [newRepo, setNewRepo] = useState("");

  useEffect(() => {
    Promise.all([fetchGlobalConfig(), fetchRepos()])
      .then(([configRes, reposRes]) => {
        setConfigYaml(configRes.config_yaml);
        setSavedYaml(configRes.config_yaml);
        setRepos(reposRes.items);
      })
      .catch(() => notifications.show({ color: "red", message: "Failed to load settings" }))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveConfig = useCallback(async () => {
    try {
      const res = await updateGlobalConfig(configYaml);
      setSavedYaml(res.config_yaml);
      notifications.show({ color: "green", message: "Config saved" });
    } catch (e) {
      notifications.show({ color: "red", message: String(e) });
    }
  }, [configYaml]);

  const handleAddRepo = useCallback(async () => {
    if (!newRepo.trim()) return;
    try {
      await registerRepo(newRepo.trim());
      setNewRepo("");
      const res = await fetchRepos();
      setRepos(res.items);
      notifications.show({ color: "green", message: "Repository added" });
    } catch (e) {
      notifications.show({ color: "red", message: String(e) });
    }
  }, [newRepo]);

  const handleRemoveRepo = useCallback(async (path: string) => {
    try {
      await unregisterRepo(path);
      setRepos((prev) => prev.filter((r) => r !== path));
      notifications.show({ color: "green", message: "Repository removed" });
    } catch (e) {
      notifications.show({ color: "red", message: String(e) });
    }
  }, []);

  const handleCleanup = useCallback(async () => {
    try {
      await cleanupWorktrees();
      notifications.show({ color: "green", message: "Worktrees cleaned up" });
    } catch (e) {
      notifications.show({ color: "red", message: String(e) });
    }
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <Loader size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <Title order={3} mb="lg">Settings</Title>

      <Stack gap="lg">
        {/* Repositories */}
        <Paper radius="lg" p="lg">
          <Text size="sm" fw={600} mb="md">
            Repositories ({repos.length})
          </Text>

          <Group gap="xs" mb="md">
            <TextInput
              placeholder="Local path or git URL"
              value={newRepo}
              onChange={(e) => setNewRepo(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddRepo()}
              className="flex-1"
              size="sm"
            />
            <Button
              size="sm"
              leftSection={<Plus size={14} />}
              disabled={!newRepo.trim()}
              onClick={handleAddRepo}
            >
              Add
            </Button>
          </Group>

          {repos.length === 0 ? (
            <Text size="sm" c="dimmed" ta="center" py="md">
              No repositories registered
            </Text>
          ) : (
            <Stack gap={4}>
              {repos.map((r) => (
                <Group
                  key={r}
                  justify="space-between"
                  className="px-3 py-2 rounded-md hover:bg-[var(--mantine-color-dark-6)] group"
                >
                  <Text size="sm" ff="monospace" c="dimmed" truncate className="flex-1" title={r}>
                    {r}
                  </Text>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="sm"
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleRemoveRepo(r)}
                  >
                    <Trash2 size={14} />
                  </ActionIcon>
                </Group>
              ))}
            </Stack>
          )}
        </Paper>

        {/* Global Config */}
        <Paper radius="lg" p="lg">
          <Text size="sm" fw={600} mb="md">Global Configuration</Text>
          <Textarea
            value={configYaml}
            onChange={(e) => setConfigYaml(e.currentTarget.value)}
            styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)", fontSize: 12 } }}
            minRows={12}
            autosize
            maxRows={30}
          />
          <Group justify="flex-end" mt="sm" gap="xs">
            <Button
              variant="subtle"
              size="xs"
              disabled={configYaml === savedYaml}
              onClick={() => setConfigYaml(savedYaml)}
            >
              Reset
            </Button>
            <Button
              size="xs"
              disabled={configYaml === savedYaml}
              onClick={handleSaveConfig}
            >
              Save Config
            </Button>
          </Group>
        </Paper>

        {/* Maintenance */}
        <Paper radius="lg" p="lg">
          <Text size="sm" fw={600} mb="md">Maintenance</Text>
          <Button
            variant="light"
            size="sm"
            leftSection={<Wrench size={14} />}
            onClick={handleCleanup}
          >
            Clean Up Worktrees
          </Button>
        </Paper>
      </Stack>
    </div>
  );
}
