import { expect, test } from "@playwright/test";
import type { ChildProcess } from "node:child_process";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { dirname, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const DEFAULT_BASE_URL = "http://127.0.0.1:18765";
const JIRA_TOKEN = "local-e2e-token";
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

let backend: ChildProcess | undefined;
let backendOutput = "";
let codeplaneHome = "";
let jiraStatus = "To Do";
let jiraRequestCount = 0;
let closeJira: (() => Promise<void>) | undefined;
let backendBaseUrl = "";
let projectId = "";
let backendSpawnError: Error | undefined;

interface TrackerLinksResponse {
  trackerLinks: Array<{
    id: string;
    summary: {
      tickets: Array<{ title: string; status: string }>;
      lastSyncedAt: string | null;
      lastError: string | null;
    } | null;
  }>;
}

async function requestJson<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: init?.body
      ? { "Content-Type": "application/json", ...init.headers }
      : init?.headers,
  });
  if (!response.ok) {
    throw new Error(
      `${init?.method ?? "GET"} ${url} failed: ${response.status} ${await response.text()}`,
    );
  }
  return response.json() as Promise<T>;
}

async function startFakeJira(): Promise<string> {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    if (request.method === "GET" && url.pathname === "/rest/api/3/search/jql") {
      const validRequest =
        request.headers.authorization === `Bearer ${JIRA_TOKEN}` &&
        url.searchParams.get("jql")?.includes('project = "TEST"') &&
        url.searchParams.get("fields") === "summary,status" &&
        url.searchParams.get("maxResults") === "100";
      if (!validRequest) {
        response.writeHead(400, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ error: "invalid Jira request" }));
        return;
      }
      jiraRequestCount += 1;
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          issues: [
            {
              id: "10001",
              key: "TEST-1",
              fields: {
                summary: "Deterministic Jira ticket",
                status: { name: jiraStatus },
              },
            },
          ],
        }),
      );
      return;
    }
    response.writeHead(404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ error: "not found" }));
  });

  await new Promise<void>((resolveReady, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveReady);
  });
  const address = server.address() as AddressInfo;
  closeJira = () =>
    new Promise<void>((resolveClosed, reject) => {
      if (!server.listening) {
        resolveClosed();
        return;
      }
      server.close((error) => (error ? reject(error) : resolveClosed()));
    });
  return `http://127.0.0.1:${address.port}`;
}

async function waitForBackend(url: string): Promise<void> {
  const deadline = Date.now() + 120_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    if (backendSpawnError) {
      throw new Error(`CodePlane failed to start: ${backendSpawnError.message}`);
    }
    if (backend && (backend.exitCode !== null || backend.signalCode !== null)) {
      throw new Error(
        `CodePlane exited before becoming ready (${backend.exitCode ?? backend.signalCode}).\n${backendOutput}`,
      );
    }
    try {
      const response = await fetch(`${url}/api/health`);
      if (response.ok) return;
      lastError = `${response.status} ${await response.text()}`;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500));
  }
  throw new Error(
    `CodePlane did not become ready: ${String(lastError)}\n${backendOutput}`,
  );
}

async function assertPortAvailable(port: number): Promise<void> {
  const probe = createServer();
  await new Promise<void>((resolveReady, reject) => {
    probe.once("error", reject);
    probe.listen(port, "127.0.0.1", resolveReady);
  });
  await new Promise<void>((resolveClosed, reject) => {
    probe.close((error) => (error ? reject(error) : resolveClosed()));
  });
}

async function stopProcess(child: ChildProcess): Promise<void> {
  if (
    child.exitCode !== null ||
    child.signalCode !== null ||
    child.pid === undefined
  ) {
    return;
  }
  const exited = new Promise<void>((resolveExit) =>
    child.once("exit", () => resolveExit()),
  );
  if (process.platform === "win32") {
    const result = spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      encoding: "utf8",
    });
    if (result.status !== 0) {
      throw new Error(`taskkill failed: ${result.stderr || result.stdout}`);
    }
  } else {
    process.kill(-child.pid, "SIGTERM");
  }

  const exitedPromptly = await Promise.race([
    exited.then(() => true),
    new Promise<false>((resolveTimeout) =>
      setTimeout(() => resolveTimeout(false), 5_000),
    ),
  ]);
  if (!exitedPromptly && process.platform !== "win32") {
    process.kill(-child.pid, "SIGKILL");
    await exited;
  } else if (!exitedPromptly) {
    throw new Error(`CodePlane process ${child.pid} did not exit after taskkill`);
  }
}

async function cleanup(): Promise<void> {
  const results = await Promise.allSettled([
    backend ? stopProcess(backend) : Promise.resolve(),
  ]);
  results.push(
    ...(await Promise.allSettled([
      closeJira ? closeJira() : Promise.resolve(),
      codeplaneHome
        ? rm(codeplaneHome, { recursive: true, force: true })
        : Promise.resolve(),
    ])),
  );
  const failures = results.filter(
    (result): result is PromiseRejectedResult => result.status === "rejected",
  );
  if (failures.length > 0) {
    throw new AggregateError(
      failures.map((failure) => failure.reason),
      "Tracker E2E cleanup failed",
    );
  }
}

async function waitForScheduledSummary(): Promise<TrackerLinksResponse> {
  const deadline = Date.now() + 80_000;
  let lastObserved: TrackerLinksResponse | undefined;
  while (Date.now() < deadline) {
    lastObserved = await requestJson<TrackerLinksResponse>(
      `${backendBaseUrl}/api/projects/${projectId}/tracker-links`,
    );
    const ticket = lastObserved.trackerLinks[0]?.summary?.tickets[0];
    if (
      ticket?.title === "Deterministic Jira ticket" &&
      ticket.status === "To Do"
    ) {
      return lastObserved;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 750));
  }
  throw new Error(
    `Scheduled tracker summary was not persisted. Last response: ${JSON.stringify(lastObserved)}`,
  );
}

test.beforeAll(async () => {
  backendBaseUrl =
    process.env.CODEPLANE_TRACKER_E2E_BASE_URL ?? DEFAULT_BASE_URL;
  const parsedBaseUrl = new URL(backendBaseUrl);
  backendBaseUrl = parsedBaseUrl.origin;
  const backendPort = Number(parsedBaseUrl.port);

  try {
    if (
      parsedBaseUrl.protocol !== "http:" ||
      parsedBaseUrl.hostname !== "127.0.0.1" ||
      parsedBaseUrl.pathname !== "/" ||
      parsedBaseUrl.search !== "" ||
      parsedBaseUrl.hash !== "" ||
      !Number.isInteger(backendPort) ||
      backendPort < 1
    ) {
      throw new Error(
        "CODEPLANE_TRACKER_E2E_BASE_URL must be an http://127.0.0.1 URL with an explicit port",
      );
    }
    await assertPortAvailable(backendPort);
    const jiraBaseUrl = await startFakeJira();
    codeplaneHome = await mkdtemp(resolve(repoRoot, ".tracker-e2e-"));

    const launchScript = [
      "from backend.persistence.database import run_migrations",
      "run_migrations()",
      "import uvicorn",
      "from backend.app_factory import create_app",
      `uvicorn.run(create_app(), host="127.0.0.1", port=${backendPort}, log_level="warning")`,
    ].join("; ");

    backend = spawn(
      "uv",
      ["run", "--no-sync", "python", "-c", launchScript],
      {
        cwd: repoRoot,
        detached: true,
        env: {
          ...process.env,
          CODEPLANE_HOME: codeplaneHome,
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
        },
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    backend.once("error", (error) => {
      backendSpawnError = error;
    });
    backend.stdout?.on("data", (chunk) => {
      backendOutput += chunk.toString();
    });
    backend.stderr?.on("data", (chunk) => {
      backendOutput += chunk.toString();
    });

    await waitForBackend(backendBaseUrl);
    const project = await requestJson<{ id: string }>(
      `${backendBaseUrl}/api/settings/projects`,
      {
        method: "POST",
        body: JSON.stringify({
          name: "Tracker E2E Project",
          repoPaths: [repoRoot],
        }),
      },
    );
    projectId = project.id;
    const credential = await requestJson<{ id: string }>(
      `${backendBaseUrl}/api/settings/credentials`,
      {
        method: "POST",
        body: JSON.stringify({
          provider: "jira",
          label: "Local Jira",
          baseUrl: jiraBaseUrl,
          pat: JIRA_TOKEN,
        }),
      },
    );
    await requestJson(
      `${backendBaseUrl}/api/projects/${projectId}/tracker-links`,
      {
        method: "POST",
        body: JSON.stringify({
          credentialId: credential.id,
          externalRef: "TEST",
        }),
      },
    );
  } catch (error) {
    try {
      await cleanup();
    } catch (cleanupError) {
      throw new AggregateError(
        [error, cleanupError],
        "Tracker E2E setup and cleanup failed",
      );
    }
    throw error;
  }
});

test.afterAll(async () => {
  await cleanup();
});

test("scheduled Jira sync persists and renders before manual refresh", async ({
  page,
}) => {
  const initial = await requestJson<TrackerLinksResponse>(
    `${backendBaseUrl}/api/projects/${projectId}/tracker-links`,
  );
  expect(initial.trackerLinks).toHaveLength(1);

  await waitForScheduledSummary();
  expect(jiraRequestCount).toBeGreaterThanOrEqual(1);

  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto(`${backendBaseUrl}/settings`);
  await expect(
    page.getByText("Deterministic Jira ticket", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("To Do", { exact: true })).toBeVisible();

  jiraStatus = "In Progress";
  const requestsBeforeRefresh = jiraRequestCount;
  await page.getByRole("button", { name: "Refresh TEST" }).click();
  await expect(page.getByText("In Progress", { exact: true })).toBeVisible();
  expect(jiraRequestCount).toBeGreaterThanOrEqual(requestsBeforeRefresh + 1);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
