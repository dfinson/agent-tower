/**
 * API client for the custom metrics chat composer and pinned metrics.
 */

import { request } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MetricsChatMessage {
  messageId: string;
  narrative: string;
  error: boolean;
  title?: string;
  viz?: string;
  vizConfig?: Record<string, unknown>;
  vizData?: unknown[];
  sqlQueries?: string[];
  suggestion?: string;
}

export interface MetricsChatResponse {
  conversationId: string;
  message: MetricsChatMessage;
}

export interface CustomMetric {
  id: string;
  name: string;
  sql: string;
  viz: string;
  vizConfig?: Record<string, unknown>;
  periodRelative: boolean;
  pinDashboard: boolean;
  pinJobPanel: boolean;
  alertEnabled: boolean;
  alertOp?: string;
  alertValue?: number;
  alertSeverity?: string;
  alertCooldownHours?: number;
  tileSize: string;
  position: number;
  originalQuestion?: string;
  explanation?: string;
  createdAt: string;
  updatedAt: string;
}

export interface CustomMetricWithData {
  metric: CustomMetric;
  data: unknown[];
  error?: string;
}

export interface CustomMetricsListResponse {
  metrics: CustomMetricWithData[];
}

export interface Conversation {
  conversationId: string;
  startedAt: string;
  lastMessageAt: string;
  messageCount: number;
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export async function sendMetricsChatMessage(
  question: string,
  conversationId?: string,
  periodDays?: number,
): Promise<MetricsChatResponse> {
  return request<MetricsChatResponse>("/metrics/chat", {
    method: "POST",
    body: JSON.stringify({
      question,
      conversationId: conversationId ?? null,
      periodDays: periodDays ?? null,
    }),
  });
}

export async function listMetricsChatConversations(): Promise<{ conversations: Conversation[] }> {
  return request("/metrics/chat/conversations");
}

// ---------------------------------------------------------------------------
// Custom Metrics CRUD
// ---------------------------------------------------------------------------

export async function listCustomMetrics(): Promise<CustomMetricsListResponse> {
  return request<CustomMetricsListResponse>("/metrics");
}

export async function pinMetric(data: {
  name: string;
  sql: string;
  viz: string;
  vizConfig?: Record<string, unknown>;
  periodRelative?: boolean;
  pinDashboard?: boolean;
  pinJobPanel?: boolean;
  tileSize?: string;
  originalQuestion?: string;
  explanation?: string;
}): Promise<CustomMetric> {
  return request<CustomMetric>("/metrics", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateMetric(
  metricId: string,
  updates: Partial<{
    name: string;
    tileSize: string;
    position: number;
    pinDashboard: boolean;
    pinJobPanel: boolean;
    alertEnabled: boolean;
    alertOp: string;
    alertValue: number;
    alertSeverity: string;
    alertCooldownHours: number;
  }>,
): Promise<CustomMetric> {
  return request<CustomMetric>(`/metrics/${metricId}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export async function deleteMetric(metricId: string): Promise<void> {
  return request(`/metrics/${metricId}`, { method: "DELETE" });
}
