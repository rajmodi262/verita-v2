import { describe, expect, it } from "vitest";

import { compact, integer, usd, usdShort } from "./format";
import { bandPath, linePath, linear, niceMax, niceStep, ticks } from "./scale";

describe("scale", () => {
  it("maps domain to range, including inverted ranges", () => {
    const y = linear([0, 10], [100, 0]);
    expect(y(0)).toBe(100);
    expect(y(5)).toBe(50);
    expect(y(10)).toBe(0);
  });

  it("survives a zero-width domain", () => {
    expect(linear([3, 3], [0, 10])(3)).toBe(0);
  });

  it("picks 1-2-5 steps", () => {
    expect(niceStep(0, 100, 5)).toBe(20);
    expect(niceStep(0, 1, 4)).toBe(0.2);
    expect(niceStep(0, 0)).toBe(1);
    expect(ticks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    expect(ticks(0.83, 1, 4)).toEqual([0.85, 0.9, 0.95, 1]);
  });

  it("rounds maxima up to a tick", () => {
    expect(niceMax(87)).toBe(100);
    expect(niceMax(0)).toBe(1);
  });

  it("builds paths", () => {
    expect(
      linePath([
        [0, 0],
        [10, 5],
      ]),
    ).toBe("M0.0,0.0L10.0,5.0");
    expect(bandPath([0, 10], [1, 2], [0, 0])).toBe("M0.0,1.0L10.0,2.0L10.0,0.0L0.0,0.0Z");
    expect(bandPath([], [], [])).toBe("");
  });
});

describe("number formats", () => {
  it("formats money and counts", () => {
    expect(usd(1234567.6)).toBe("$1,234,568");
    expect(compact(950)).toBe("950");
    expect(compact(12_400)).toBe("12.4k");
    expect(compact(3_100_000)).toBe("3.1M");
    expect(integer(1234.4)).toBe("1,234");
    expect(usdShort(2145)).toBe("$2,145");
    expect(usdShort(354_282_913)).toBe("$354.3M");
    expect(usdShort(1_902_585_559)).toBe("$1.90B");
  });
});
