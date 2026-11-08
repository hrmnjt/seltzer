import { describe, expect, it } from "vitest";
import type { BoardSnapshot, CardTile } from "../api/client";
import { lanesOf, MAYBE } from "./board";
import { keyBetween } from "./ordering";

describe("keyBetween", () => {
  it("keeps keys ordered under random inserts", () => {
    const keys: string[] = [];
    let seed = 7;
    const rand = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
    for (let n = 0; n < 1000; n++) {
      const i = Math.floor(rand() * (keys.length + 1));
      const key = keyBetween(keys[i - 1] ?? null, keys[i] ?? null);
      if (i > 0) expect(key > keys[i - 1]!).toBe(true);
      if (i < keys.length) expect(key < keys[i]!).toBe(true);
      keys.splice(i, 0, key);
    }
  });

  it("matches the server's first keys", () => {
    // Mirrors seltzer/ordering.py: the midpoint of an empty list is "V".
    expect(keyBetween(null, null)).toBe("V");
    expect(keyBetween(null, "V")).toBe("G");
    expect(keyBetween("V", null)).toBe("l");
  });
});

describe("lanesOf", () => {
  const tile = (over: Partial<CardTile>): CardTile =>
    ({ id: "x", golden: false, last_active_at: "2026-11-01T00:00:00Z", column_id: null, tags: [], assignee_ids: [], closing_soon: false, ...over }) as CardTile;

  it("puts golden cards first, then the most recently active", () => {
    const snap = {
      columns: [{ id: "c1", name: "Doing", color: "blue", position: "V" }],
      cards: [
        tile({ id: "a", last_active_at: "2026-11-01T09:00:00Z" }),
        tile({ id: "b", last_active_at: "2026-10-01T09:00:00Z", golden: true }),
        tile({ id: "c", last_active_at: "2026-11-03T09:00:00Z" }),
        tile({ id: "d", column_id: "c1" }),
      ],
    } as unknown as BoardSnapshot;
    const lanes = lanesOf(snap);
    expect(lanes[MAYBE]).toEqual(["b", "c", "a"]);
    expect(lanes.c1).toEqual(["d"]);
  });
});
