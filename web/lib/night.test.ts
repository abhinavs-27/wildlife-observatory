import assert from "node:assert/strict";
import { test } from "node:test";
import { heroTitle, lastNightWindow, moonPhase } from "./night.ts";
import { portraitStyle } from "./portrait.ts";

test("last night window, New York, midday", () => {
  const w = lastNightWindow(new Date("2026-11-21T17:00:00Z"), "America/New_York");
  assert.equal(w.from, "2026-11-20T23:00:00.000Z"); // 6 pm EST
  assert.equal(w.to, "2026-11-21T12:00:00.000Z"); // 7 am EST
});

test("last night window before 7 am local is the night ending now", () => {
  const w = lastNightWindow(new Date("2026-11-21T08:00:00Z"), "America/New_York"); // 3 am EST
  assert.equal(w.to, "2026-11-21T12:00:00.000Z");
});

test("portrait crop clamps at the image edge", () => {
  const s = portraitStyle([0, 0.4, 0.2, 0.2]);
  assert.match(s.backgroundPosition, /^0% /);
  assert.equal(s.backgroundSize, "375%");
});

test("moon phase at a known new moon", () => {
  const m = moonPhase(new Date(Date.UTC(2000, 0, 6, 18, 14)));
  assert.ok(m.illumination < 0.02);
  assert.equal(m.name, "New moon");
});

test("hero title is honest about uncertainty", () => {
  assert.equal(heroTitle([{ species: "squirrel family", count: 1, uncertain: true }]), "Possibly a squirrel family");
  assert.equal(heroTitle([{ species: "pending", count: 1, uncertain: false }]), "Identifying…");
  assert.equal(heroTitle([{ species: "red fox", count: 1, uncertain: false }]), "Red fox");
});
