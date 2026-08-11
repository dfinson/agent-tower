import { describe, expect, it } from "vitest";
import { matchesNameFilter } from "./nameFilter";

describe("matchesNameFilter", () => {
  it("matches everything when the query is empty", () => {
    expect(matchesNameFilter("Alpha", "")).toBe(true);
  });

  it("matches everything when the query is whitespace-only", () => {
    expect(matchesNameFilter("Alpha", "   ")).toBe(true);
  });

  it("matches a partial, case-insensitive substring", () => {
    expect(matchesNameFilter("My Project", "project")).toBe(true);
    expect(matchesNameFilter("My Project", "PROJ")).toBe(true);
    expect(matchesNameFilter("My Project", "y pr")).toBe(true);
  });

  it("trims leading/trailing whitespace from the query", () => {
    expect(matchesNameFilter("My Project", "  project  ")).toBe(true);
  });

  it("returns false when there is no match", () => {
    expect(matchesNameFilter("My Project", "xyz")).toBe(false);
  });

  it("returns false for an empty name with a non-empty query", () => {
    expect(matchesNameFilter("", "xyz")).toBe(false);
  });
});
