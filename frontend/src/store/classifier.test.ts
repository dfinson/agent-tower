import { describe, it, expect } from "vitest";
import { isActiveJob, isSignoffJob, isAttentionJob, isDoneJob } from "./selectors";
import type { JobSummary } from "./types";
import type { components } from "../api/schema";

/**
 * AD-1a — board classifier totality.
 *
 * The four board predicates must partition the ENTIRE state × resolution space of an
 * unarchived job into exactly one column. This is not a style rule, it is a
 * visibility guarantee:
 *
 *   - a job matching NO predicate renders on no board column, and because History
 *     lists archived jobs only, it is invisible in the entire UI. This actually
 *     shipped: `completed` + `merged` + `archivedAt: null` jobs (and every
 *     `canceled` job) matched nothing and silently disappeared.
 *   - a job matching TWO predicates renders twice and inflates two count badges.
 *
 * `JobState` and `Resolution` are taken from the generated OpenAPI schema, so adding a
 * backend enum member without extending a predicate fails this test by construction.
 */

type JobState = components["schemas"]["JobState"];
type Resolution = components["schemas"]["Resolution"];

const ALL_STATES: readonly JobState[] = [
  "preparing",
  "queued",
  "running",
  "waiting_for_approval",
  "review",
  "completed",
  "failed",
  "canceled",
];

const ALL_RESOLUTIONS: readonly (Resolution | null)[] = [
  null,
  "unresolved",
  "merged",
  "pr_created",
  "discarded",
  "conflict",
];

function makeJob(state: JobState, resolution: Resolution | null, archivedAt: string | null = null): JobSummary {
  return {
    id: `job-${state}-${resolution ?? "null"}`,
    repo: "/repo/alpha",
    projectId: "project-alpha",
    state,
    resolution,
    archivedAt,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    prompt: "prompt",
  } as unknown as JobSummary;
}

const COLUMNS: readonly { name: string; predicate: (j: JobSummary) => boolean }[] = [
  { name: "In Progress", predicate: isActiveJob },
  { name: "Awaiting Input", predicate: isSignoffJob },
  { name: "Failed", predicate: isAttentionJob },
  { name: "Done", predicate: isDoneJob },
];

function columnsFor(job: JobSummary): string[] {
  return COLUMNS.filter((c) => c.predicate(job)).map((c) => c.name);
}

describe("board classifier totality (AD-1a)", () => {
  it("assigns every unarchived state × resolution cell to exactly one column", () => {
    const offenders: string[] = [];

    for (const state of ALL_STATES) {
      for (const resolution of ALL_RESOLUTIONS) {
        const matched = columnsFor(makeJob(state, resolution));
        if (matched.length !== 1) {
          offenders.push(
            `${state} + ${resolution ?? "(null)"} => ${matched.length === 0 ? "NO COLUMN (invisible in the entire UI)" : `${matched.length} columns: ${matched.join(", ")}`}`,
          );
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it("covers the full cartesian space, so the guarantee above is not vacuous", () => {
    expect(ALL_STATES.length * ALL_RESOLUTIONS.length).toBe(48);
  });

  it("keeps every archived job off the board entirely", () => {
    for (const state of ALL_STATES) {
      for (const resolution of ALL_RESOLUTIONS) {
        const archived = makeJob(state, resolution, "2026-01-02T00:00:00Z");
        expect(columnsFor(archived)).toEqual([]);
      }
    }
  });
});

describe("Done column semantics", () => {
  it("holds landed work: merged and pr_created", () => {
    expect(columnsFor(makeJob("completed", "merged"))).toEqual(["Done"]);
    expect(columnsFor(makeJob("completed", "pr_created"))).toEqual(["Done"]);
  });

  it("holds conclusions the operator already made: discarded and canceled", () => {
    expect(columnsFor(makeJob("completed", "discarded"))).toEqual(["Done"]);
    expect(columnsFor(makeJob("canceled", null))).toEqual(["Done"]);
    expect(columnsFor(makeJob("canceled", "merged"))).toEqual(["Done"]);
  });

  it("does NOT hold conflicts — those still need a human, so they stay in Awaiting Input", () => {
    expect(columnsFor(makeJob("completed", "conflict"))).toEqual(["Awaiting Input"]);
  });

  it("does NOT hold completed-but-undecided work", () => {
    expect(columnsFor(makeJob("completed", null))).toEqual(["Awaiting Input"]);
    expect(columnsFor(makeJob("completed", "unresolved"))).toEqual(["Awaiting Input"]);
  });

  it("keeps merged work on the board until it is archived — merging alone never removes it", () => {
    const merged = makeJob("completed", "merged");
    expect(columnsFor(merged)).toEqual(["Done"]);

    const archived = makeJob("completed", "merged", "2026-01-02T00:00:00Z");
    expect(columnsFor(archived)).toEqual([]);
  });
});

describe("regression: the limbo cells that shipped invisible", () => {
  const LIMBO: readonly [JobState, Resolution | null][] = [
    ["completed", "merged"],
    ["completed", "pr_created"],
    ["completed", "discarded"],
    ["completed", "conflict"],
    ["canceled", null],
    ["canceled", "unresolved"],
    ["canceled", "merged"],
    ["canceled", "pr_created"],
    ["canceled", "discarded"],
    ["canceled", "conflict"],
  ];

  it.each(LIMBO)("%s + %s now has exactly one home", (state, resolution) => {
    expect(columnsFor(makeJob(state, resolution))).toHaveLength(1);
  });
});
