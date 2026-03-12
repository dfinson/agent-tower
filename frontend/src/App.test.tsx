import { describe, it, expect } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("exports a component", () => {
    expect(App).toBeDefined();
    expect(typeof App).toBe("function");
  });
});
