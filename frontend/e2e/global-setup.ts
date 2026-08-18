/**
 * Playwright global setup for the live-server E2E suite.
 *
 * The suite runs against a real CodePlane server (see playwright.config.ts
 * webServer) backed by a fresh SQLite database with zero registered
 * Projects. Several specs (codeplane.spec.ts, edge-cases.spec.ts) exercise
 * the actual root "/" route rather than mocking `/api/settings/projects`,
 * so they need at least one real Project to exist for the Projects
 * overview and sidebar Project list to render their non-empty state.
 *
 * This registers the checked-out repository itself as a Project against
 * the running server, once, before any test executes.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { FullConfig } from "@playwright/test";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use?.baseURL ?? "http://127.0.0.1:8080";
  const repoPath = path.resolve(dirname, "..", "..");

  const res = await fetch(`${baseURL}/api/settings/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "CodePlane", repoPaths: [repoPath] }),
  });

  // 201 = created; 409 means a prior run already registered it (e.g. a
  // reused dev server outside CI) — both are fine to proceed with.
  if (!res.ok && res.status !== 409) {
    const body = await res.text().catch(() => "<no body>");
    throw new Error(
      `global-setup: failed to seed a Project for E2E (status ${res.status}): ${body}`,
    );
  }
}
