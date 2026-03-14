/**
 * TelemetryPanel — collapsible telemetry display on job cards/detail.
 *
 * Shows: tokens, tool calls, context window, model, timings.
 * Loads telemetry lazily when expanded.
 */
import { useState, useEffect } from "react";
import {
  Paper, Group, Text, Stack, Collapse, UnstyledButton, Badge, Progress, Loader,
} from "@mantine/core";
import { BarChart3, ChevronDown, ChevronRight, Cpu, Clock, Wrench, MessageSquare } from "lucide-react";
import { fetchJobTelemetry } from "../api/client";

interface TelemetryData {
  available: boolean;
  model?: string;
  durationMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  contextWindowSize?: number;
  toolCallCount?: number;
  totalToolDurationMs?: number;
  toolCalls?: { name: string; durationMs: number; success: boolean }[];
  approvalCount?: number;
  agentMessages?: number;
  operatorMessages?: number;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

export function TelemetryPanel({ jobId }: { jobId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<TelemetryData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expanded || data) return;
    setLoading(true);
    fetchJobTelemetry(jobId)
      .then(setData)
      .catch(() => setData({ available: false }))
      .finally(() => setLoading(false));
  }, [expanded, data, jobId]);

  return (
    <Paper radius="lg" p={0} className="overflow-hidden">
      <UnstyledButton
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-[var(--mantine-color-dark-6)] transition-colors"
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <BarChart3 size={14} />
        <Text size="sm" fw={600} c="dimmed">Telemetry</Text>
        {data?.available && data.totalTokens ? (
          <Badge size="xs" variant="light" ml="auto">
            {formatTokens(data.totalTokens)} tokens
          </Badge>
        ) : null}
      </UnstyledButton>

      <Collapse in={expanded}>
        <div className="px-4 pb-4 border-t border-[var(--mantine-color-dark-4)]">
          {loading ? (
            <div className="flex justify-center py-4"><Loader size="sm" /></div>
          ) : !data?.available ? (
            <Text size="sm" c="dimmed" py="sm">No telemetry data available</Text>
          ) : (
            <Stack gap="md" mt="sm">
              {/* Token usage */}
              <div>
                <Group gap="xs" mb={6}>
                  <Cpu size={14} className="text-[var(--mantine-color-blue-5)]" />
                  <Text size="xs" fw={600} c="dimmed">Token Usage</Text>
                </Group>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <Text size="lg" fw={700}>{formatTokens(data.promptTokens ?? 0)}</Text>
                    <Text size="xs" c="dimmed">Prompt</Text>
                  </div>
                  <div>
                    <Text size="lg" fw={700}>{formatTokens(data.completionTokens ?? 0)}</Text>
                    <Text size="xs" c="dimmed">Completion</Text>
                  </div>
                  <div>
                    <Text size="lg" fw={700}>{formatTokens(data.totalTokens ?? 0)}</Text>
                    <Text size="xs" c="dimmed">Total</Text>
                  </div>
                </div>
                {data.contextWindowSize ? (
                  <div className="mt-2">
                    <Group justify="space-between" mb={4}>
                      <Text size="xs" c="dimmed">Context window</Text>
                      <Text size="xs" c="dimmed">
                        {formatTokens(data.totalTokens ?? 0)} / {formatTokens(data.contextWindowSize)}
                      </Text>
                    </Group>
                    <Progress
                      value={Math.min(100, ((data.totalTokens ?? 0) / data.contextWindowSize) * 100)}
                      size="sm"
                      radius="xl"
                      color={((data.totalTokens ?? 0) / data.contextWindowSize) > 0.8 ? "red" : "blue"}
                    />
                  </div>
                ) : null}
              </div>

              {/* Model & Duration */}
              <Group gap="lg">
                {data.model && (
                  <div>
                    <Text size="xs" c="dimmed">Model</Text>
                    <Badge variant="light" size="sm">{data.model}</Badge>
                  </div>
                )}
                {data.durationMs ? (
                  <div>
                    <Group gap={4}>
                      <Clock size={12} className="text-[var(--mantine-color-dimmed)]" />
                      <Text size="xs" c="dimmed">Duration</Text>
                    </Group>
                    <Text size="sm" fw={600}>{formatDuration(data.durationMs)}</Text>
                  </div>
                ) : null}
                <div>
                  <Group gap={4}>
                    <MessageSquare size={12} className="text-[var(--mantine-color-dimmed)]" />
                    <Text size="xs" c="dimmed">Messages</Text>
                  </Group>
                  <Text size="sm">{data.agentMessages ?? 0} agent / {data.operatorMessages ?? 0} operator</Text>
                </div>
              </Group>

              {/* Tool calls */}
              {(data.toolCallCount ?? 0) > 0 && (
                <div>
                  <Group gap="xs" mb={6}>
                    <Wrench size={14} className="text-[var(--mantine-color-yellow-5)]" />
                    <Text size="xs" fw={600} c="dimmed">
                      Tool Calls ({data.toolCallCount})
                    </Text>
                    <Text size="xs" c="dimmed" ml="auto">
                      {formatDuration(data.totalToolDurationMs ?? 0)} total
                    </Text>
                  </Group>
                  <Stack gap={2}>
                    {(data.toolCalls ?? []).slice(-10).map((tc, i) => (
                      <Group key={i} justify="space-between" className="px-2 py-1 rounded text-xs bg-[var(--mantine-color-dark-7)]">
                        <Group gap="xs">
                          <div className={`w-1.5 h-1.5 rounded-full ${tc.success ? "bg-green-500" : "bg-red-500"}`} />
                          <Text size="xs" ff="monospace">{tc.name}</Text>
                        </Group>
                        <Text size="xs" c="dimmed">{formatDuration(tc.durationMs)}</Text>
                      </Group>
                    ))}
                  </Stack>
                </div>
              )}
            </Stack>
          )}
        </div>
      </Collapse>
    </Paper>
  );
}
