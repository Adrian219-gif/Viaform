import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mergeReusableEvidence, readReusableEvidence, SPECIAL_EVIDENCE_CACHE_KEY, writeReusableEvidence } from "../src/features/special-interview/evidence-cache.ts";
import { specialInterviewCompletion } from "../src/features/special-interview/completion.ts";

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
assert.ok(!renderer.includes("OR 课程组满足一项后即可继续"), "generic OR validation fallback must be removed");

const concrete = (key: string) => ({ evidence_key: key, prerequisite_kind: "concrete_course" as const, canonical_label: key, category_label: null, minimum_courses: null });
const category = (key: string, minimum: number) => ({ evidence_key: key, prerequisite_kind: "course_category" as const, canonical_label: null, category_label: key, minimum_courses: minimum });
const basePlan = {
  prerequisite_groups: [{ relation: "all_of" as const, courses: [concrete("oop"), concrete("algorithms"), concrete("complexity")] }],
  objective_special_requirements: [],
  aggregate_course_credits: [],
};
const concreteComplete = specialInterviewCompletion(basePlan, { oop: "known", algorithms: "known", complexity: "known" }, {}, {});
assert.equal(concreteComplete.completedCount, 3);
assert.equal(concreteComplete.canSubmit, true, "all concrete courses are complete without optional course names");

const categoryPlan = {
  prerequisite_groups: [{ relation: "all_of" as const, courses: [category("Systems", 2)] }],
  objective_special_requirements: [],
  aggregate_course_credits: [],
};
const categoryMissing = specialInterviewCompletion(categoryPlan, { Systems: "known" }, {}, {});
assert.equal(categoryMissing.completedCount, 0);
assert.equal(categoryMissing.canSubmit, false);
assert.match(categoryMissing.validationMessage, /Systems/);
assert.doesNotMatch(categoryMissing.validationMessage, /OR/);
const categoryPartial = specialInterviewCompletion(categoryPlan, { Systems: "known" }, { Systems: ["Operating Systems"] }, {});
assert.equal(categoryPartial.canSubmit, false);
assert.match(categoryPartial.validationMessage, /还需要填写 1 门/);
const categoryComplete = specialInterviewCompletion(categoryPlan, { Systems: "known" }, { Systems: ["Operating Systems", "Distributed Systems"] }, {});
assert.equal(categoryComplete.completedCount, 1);
assert.equal(categoryComplete.canSubmit, true);
assert.equal(specialInterviewCompletion(categoryPlan, { Systems: "unknown" }, {}, {}).canSubmit, true);
assert.equal(specialInterviewCompletion(categoryPlan, { Systems: "known_negative" }, {}, {}).canSubmit, true);

const allMissing = specialInterviewCompletion(basePlan, { oop: "known" }, {}, {});
assert.equal(allMissing.canSubmit, false);
assert.match(allMissing.validationMessage, /所有必需项/);
assert.doesNotMatch(allMissing.validationMessage, /OR/);
const oneOfPlan = { ...basePlan, prerequisite_groups: [{ relation: "one_of" as const, courses: basePlan.prerequisite_groups[0].courses }] };
const oneOfPending = specialInterviewCompletion(oneOfPlan, { oop: "known_negative" }, {}, {});
assert.equal(oneOfPending.canSubmit, false);
assert.match(oneOfPending.validationMessage, /继续|完成相应选择/);
const oneOfTerminal = specialInterviewCompletion(oneOfPlan, { oop: "known_negative", algorithms: "unknown", complexity: "known_negative" }, {}, {});
assert.equal(oneOfTerminal.canSubmit, true, "all negative/unknown branches are terminal interview answers");

const creditPlan = {
  prerequisite_groups: [{ relation: "all_of" as const, courses: Array.from({ length: 7 }, (_, index) => concrete(`course-${index}`)) }],
  objective_special_requirements: [],
  aggregate_course_credits: [{ evidence_key: "credit", label: "相关课程", unit: "ECTS" }],
};
const sevenAnswers = Object.fromEntries(Array.from({ length: 7 }, (_, index) => [`course-${index}`, "known" as const]));
const creditMissing = specialInterviewCompletion(creditPlan, sevenAnswers, {}, {});
assert.equal(creditMissing.completedCount, 7);
assert.equal(creditMissing.canSubmit, false);
assert.match(creditMissing.validationMessage, /总 ECTS|不确定/);
const creditKnown = specialInterviewCompletion(creditPlan, { ...sevenAnswers, credit: "known" }, {}, { credit: "22.5" });
assert.equal(creditKnown.completedCount, 8);
assert.equal(creditKnown.canSubmit, true);
const creditUnknown = specialInterviewCompletion(creditPlan, { ...sevenAnswers, credit: "unknown" }, {}, {});
assert.equal(creditUnknown.completedCount, 8);
assert.equal(creditUnknown.canSubmit, true);

storage.setItem(SPECIAL_EVIDENCE_CACHE_KEY, "not-json");
assert.deepEqual(readReusableEvidence(storage as unknown as Storage), [], "corrupt cache must fail safely");

console.log("PASS special interview evidence persistence regressions");
