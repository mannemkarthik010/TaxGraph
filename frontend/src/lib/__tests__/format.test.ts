import { describe, expect, it } from "vitest";
import { money } from "../format";
import { evidenceTraceHref, proveHref } from "../links";

describe("money", () => {
  it("keeps ratio precision instead of rounding to a whole dollar", () => {
    expect(money(0.6347)).toBe("0.6347");   // 540NR deduction percentage (was "1")
    expect(money(0.0766)).toBe("0.0766");   // CA tax rate (was "0")
    expect(money(0.5)).toBe("0.50");
  });
  it("formats whole-dollar amounts in accounting style", () => {
    expect(money(81854)).toBe("81,854");
    expect(money(-8256)).toBe("(8,256)");
    expect(money(4220, { sign: true })).toBe("+4,220");
    expect(money(0)).toBe("0");
    expect(money(1500.6)).toBe("1,501");    // dollar amounts with cents still round to dollars
  });
  it("passes non-numbers through", () => {
    expect(money(null)).toBe("—");
    expect(money("2025-07-15")).toBe("2025-07-15");
  });
});

describe("links keep the return version", () => {
  it("evidence trace links carry the schedule's version", () => {
    expect(evidenceTraceHref("ev-0315", "v1")).toBe("/prove?ref=ev-0315&mode=down&v=v1");
    expect(evidenceTraceHref("ev-0315", "v2")).toContain("&v=v2");
  });
  it("line links derive the version from the line reference", () => {
    expect(proveHref("line:v1:SchC.44a", "impact")).toBe("/prove?ref=line%3Av1%3ASchC.44a&mode=impact&v=v1");
  });
});
