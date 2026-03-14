import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Paper, Title, Select, Textarea, TextInput, Button, Group, Stack, Text, Divider,
  Collapse, UnstyledButton,
} from "@mantine/core";
import { ChevronDown, ChevronRight, Rocket } from "lucide-react";
import { notifications } from "@mantine/notifications";
import { createJob, fetchRepos } from "../api/client";
import { VoiceRecorder } from "./VoiceButton";

export function JobCreationScreen() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<{ value: string; label: string }[]>([]);
  const [repo, setRepo] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [baseRef, setBaseRef] = useState("");
  const [branch, setBranch] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchRepos()
      .then((r) => {
        const items = r.items.map((p) => ({
          value: p,
          label: p.split("/").pop() ?? p,
        }));
        setRepos(items);
        setRepo((prev) => prev ?? items[0]?.value ?? null);
      })
      .catch(() => notifications.show({ color: "red", message: "Failed to load repos" }));
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!repo || !prompt.trim()) return;
    setSubmitting(true);
    try {
      const result = await createJob({
        repo,
        prompt: prompt.trim(),
        base_ref: baseRef || undefined,
        branch: branch || undefined,
      });
      notifications.show({ color: "green", message: `Job ${result.id} created` });
      navigate(`/jobs/${result.id}`);
    } catch (e) {
      notifications.show({ color: "red", title: "Failed", message: String(e) });
    } finally {
      setSubmitting(false);
    }
  }, [repo, prompt, baseRef, branch, navigate]);

  return (
    <div className="max-w-xl mx-auto">
      <Title order={3} mb="lg">New Job</Title>

      <Paper radius="lg" p="lg">
        <Stack gap="md">
          <Select
            label="Repository"
            placeholder="Select a repository…"
            data={repos}
            value={repo}
            onChange={setRepo}
            searchable
            size="sm"
          />

          <div>
            <Group justify="space-between" mb={6}>
              <Text size="sm" fw={500}>Prompt</Text>
              <VoiceRecorder
                onTranscript={(t) => setPrompt((p) => (p ? p + " " : "") + t)}
              />
            </Group>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.currentTarget.value)}
              placeholder="Describe the task for the agent…"
              minRows={4}
              autosize
              maxRows={12}
              size="sm"
            />
          </div>

          <Divider />

          <UnstyledButton onClick={() => setShowAdvanced(!showAdvanced)}>
            <Group gap={4}>
              {showAdvanced ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <Text size="xs" c="dimmed">Advanced options</Text>
            </Group>
          </UnstyledButton>

          <Collapse in={showAdvanced}>
            <Stack gap="sm">
              <TextInput
                label="Base Reference"
                placeholder="e.g., main"
                value={baseRef}
                onChange={(e) => setBaseRef(e.currentTarget.value)}
                size="sm"
              />
              <TextInput
                label="Branch Name"
                placeholder="Auto-generated if empty"
                value={branch}
                onChange={(e) => setBranch(e.currentTarget.value)}
                size="sm"
              />
            </Stack>
          </Collapse>

          <Group justify="flex-end" mt="sm">
            <Button variant="subtle" onClick={() => navigate("/")}>
              Cancel
            </Button>
            <Button
              leftSection={<Rocket size={16} />}
              disabled={!repo || !prompt.trim()}
              loading={submitting}
              onClick={handleSubmit}
            >
              Create Job
            </Button>
          </Group>
        </Stack>
      </Paper>
    </div>
  );
}
