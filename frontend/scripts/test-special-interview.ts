import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mergeReusableEvidence, readReusableEvidence, SPECIAL_EVIDENCE_CACHE_KEY, writeReusableEvidence } from "../src/features/special-interview/evidence-cache.ts";

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

const storage = new MemoryStorage();
const first = { key: "programme_course_response:programme-a:requirement-a:course-linear-algebra", availability: "known", value: { user_course_name: "Matrix Algebra" } };
writeReusableEvidence(storage as unknown as Storage, [first]);
assert.deepEqual(readReusableEvidence(storage as unknown as Storage), [first], "refresh must restore reusable evidence");

const second = { key: "objective_special:certificate_x", availability: "known_negative" };
const updated = { ...first, availability: "unknown" };
const merged = mergeReusableEvidence([first, second], [updated]);
assert.equal(merged.length, 2, "updating one fact must retain unrelated evidence");
assert.equal(merged.find((item) => item.key === first.key)?.availability, "unknown", "same key must overwrite the old user fact");
writeReusableEvidence(storage as unknown as Storage, merged);
assert.equal(JSON.parse(storage.values.get(SPECIAL_EVIDENCE_CACHE_KEY) ?? "[]").length, 2, "programme-scoped cache must retain merged facts");

const scopedCategory = { key: "course_category_response:programme-specific", availability: "known" };
const actualUserCourse = { key: "user_course:operating_systems", availability: "known", value: { course_name: "Operating Systems" } };
writeReusableEvidence(storage as unknown as Storage, [scopedCategory, actualUserCourse]);
assert.deepEqual(readReusableEvidence(storage as unknown as Storage), [actualUserCourse], "programme category conclusion must not enter global reusable cache");

const programmeCategory = { key: "programme_course_response:programme-a:requirement-a:course-systems", availability: "known" };
writeReusableEvidence(storage as unknown as Storage, [programmeCategory]);
assert.deepEqual(readReusableEvidence(storage as unknown as Storage), [programmeCategory], "new programme-scoped category response must survive refresh");

const renderer = readFileSync(new URL("../src/features/special-interview/SpecialRequirementInterview.tsx", import.meta.url), "utf8");
assert.ok(renderer.includes("以下课程要求均需确认"), "all_of must use user-facing copy");
assert.ok(renderer.includes("以下课程满足其中一项即可"), "one_of must use user-facing copy");
assert.ok(!renderer.includes("AND / 全部确认") && !renderer.includes("OR / 至少一项"), "engineering relation badges must not be rendered");
assert.ok(renderer.includes("suggested_user_courses"), "saved user courses should be shown only as confirmation references");

storage.setItem(SPECIAL_EVIDENCE_CACHE_KEY, "not-json");
assert.deepEqual(readReusableEvidence(storage as unknown as Storage), [], "corrupt cache must fail safely");

console.log("PASS special interview evidence persistence regressions");
