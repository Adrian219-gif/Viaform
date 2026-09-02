import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { nextStepAfterSpecialExtraction } from "../src/features/special-interview/workflow.ts";

assert.equal(nextStepAfterSpecialExtraction(3), "special_interview", "remaining items must open the new Special Interview");
assert.equal(nextStepAfterSpecialExtraction(0), "current_gap", "zero items must skip directly to current Gap");

const pageSource = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
assert.ok(!pageSource.includes('setTargetStep("gap_interview")'), "formal navigation must never enter the legacy Adaptive Gap Interview");
assert.match(pageSource, /setGapPlan\(plan\);\s*await analyzeGap\(plan, evidence\);/, "Gap planning must transition directly to Gap analysis");
assert.ok(pageSource.includes('nextStepAfterSpecialExtraction(plan.remaining_item_count)'), "both Special paths must use the explicit workflow transition");
assert.ok(!pageSource.includes('targetStep === "gap_interview" ? "04 · 补充匹配信息"'), "legacy interview must not appear in the formal header/stepper");

console.log("PASS special interview formal workflow bypass regressions");
