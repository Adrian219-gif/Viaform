import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EMPTY_STANDARD_PROFILE, STANDARD_PROFILE_STEPS, canProceedToExplore, firstMissingProfileStep, profileCompleteness, profileHasForbiddenProgrammeSpecificFields } from "../src/features/standard-profile/profile.ts";
import { STANDARD_PROFILE_MODULE_STEPS, UNIFIED_PROFILE_CACHE_KEY, mergeProfileModule, profileEntryView, readStandardProfileCache, writeStandardProfileCache } from "../src/features/standard-profile/profile-cache.ts";
import type { StandardUserProfile } from "../src/features/standard-profile/profile.ts";

function fixture(): StandardUserProfile {
  return structuredClone(EMPTY_STANDARD_PROFILE);
}

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

function completeFixture(): StandardUserProfile {
  const profile = fixture();
  profile.education.university = "University X";
  profile.education.major = "Computer Science";
  profile.education.gpa = { value: 3.6, scale: 4 };
  profile.language.IELTS_status = "none";
  profile.language.TOEFL_status = "unknown";
  profile.standardized_test.GRE_status = "none";
  profile.standardized_test.GMAT_status = "none";
  profile.materials.cv_status = "prepared";
  profile.materials.transcript_status = "prepared";
  profile.materials.degree_certificate_status = "prepared";
  profile.materials.motivation_letter_status = "not_prepared";
  profile.materials.portfolio_status = "not_prepared";
  profile.materials.confirmed_recommenders = 2;
  return profile;
}

{
  const profile = completeFixture();
  assert.deepEqual(profileCompleteness(profile), []);
  assert.deepEqual(profile.education.gpa, { value: 3.6, scale: 4 });
}
{
  const profile = completeFixture();
  profile.education.gpa = { value: 4.5, scale: 4 };
  assert(profileCompleteness(profile).some((issue) => issue.key === "education.gpa"));
}
{
  const profile = completeFixture();
  profile.education.gpa = null;
  profile.education.average_score = { value: 86, scale: 100 };
  assert.deepEqual(profileCompleteness(profile), []);
}
{
  const profile = completeFixture();
  profile.education.gpa = null;
  profile.education.average_score = null;
  assert(profileCompleteness(profile).some((issue) => issue.key === "education.academic_score"));
}
{
  const profile = completeFixture();
  profile.language.IELTS_status = "has_value";
  profile.language.IELTS = 7.5;
  assert.deepEqual(profileCompleteness(profile), []);
  assert(Object.values(profile.language.IELTS_subscores).every((value) => value === null));
}
{
  const profile = completeFixture();
  profile.standardized_test.GRE_status = "none";
  profile.standardized_test.GRE = null;
  assert(!profileCompleteness(profile).some((issue) => issue.key.includes("GRE")));
}
{
  const profile = completeFixture();
  assert.equal(profile.materials.confirmed_recommenders, 2);
  assert.equal(profile.materials.cv_status, "prepared");
  assert.equal(profile.materials.degree_certificate_status, "prepared");
  assert.equal(profile.materials.portfolio_status, "not_prepared");
}
{
  const profile = completeFixture();
  profile.education.major = "";
  profile.materials.confirmed_recommenders = null;
  const issues = profileCompleteness(profile);
  assert(issues.some((issue) => issue.key === "education.major"));
  assert(issues.some((issue) => issue.key === "materials.confirmed_recommenders"));
  assert.equal(profile.education.university, "University X");
  assert.equal(canProceedToExplore(profile, "complete"), false);
  assert.equal(canProceedToExplore(profile, "skip"), true);
}
{
  const profile = completeFixture();
  assert.equal(profileHasForbiddenProgrammeSpecificFields(profile), false);
  assert.equal(JSON.stringify(profile).includes("Linear Algebra"), false);
  assert.equal(JSON.stringify(profile).includes("Mathematics ECTS"), false);
}
{
  const storage = new MemoryStorage();
  const profile = completeFixture();
  profile.experience.research = ["historical research data"];
  profile.experience.research_status = "has_value";
  writeStandardProfileCache(storage, profile, "completed", "2026-09-01T00:00:00Z");
  assert(storage.getItem(UNIFIED_PROFILE_CACHE_KEY));
  const restored = readStandardProfileCache(storage);
  assert.equal(restored?.profileStatus, "completed");
  assert.equal(profileEntryView(restored?.profileStatus ?? "not_started"), "summary");
  assert.equal(restored?.profile.education.gpa?.value, 3.6);
  assert.equal(restored?.profile.standardized_test.GRE_status, "none");
  assert.equal(restored?.profile.materials.cv_status, "prepared");
  assert.equal(restored?.profile.materials.confirmed_recommenders, 2);
  assert.deepEqual(restored?.profile.experience.research, ["historical research data"]);
  assert.equal(restored?.profile.materials.degree_certificate_status, "prepared");
}
{
  const storage = new MemoryStorage();
  const legacy = completeFixture();
  delete (legacy.materials as Partial<StandardUserProfile["materials"]>).degree_certificate_status;
  storage.setItem(UNIFIED_PROFILE_CACHE_KEY, JSON.stringify({ version: 2, profile: legacy, profileStatus: "completed", updated_at: "2026-01-01T00:00:00Z" }));
  const restored = readStandardProfileCache(storage);
  assert.equal(restored?.profile.materials.degree_certificate_status, null);
  assert(restored?.profile);
  restored.profile.materials.degree_certificate_status = "unknown";
  writeStandardProfileCache(storage, restored.profile, "completed");
  assert.equal(readStandardProfileCache(storage)?.profile.materials.degree_certificate_status, "unknown");
}
{
  for (const status of ["prepared", "not_prepared", "unknown"] as const) {
    const profile = completeFixture();
    profile.materials.degree_certificate_status = status;
    const storage = new MemoryStorage();
    writeStandardProfileCache(storage, profile, "completed");
    assert.equal(readStandardProfileCache(storage)?.profile.materials.degree_certificate_status, status);
  }
  const profile = completeFixture();
  profile.materials.degree_certificate_status = null;
  assert(profileCompleteness(profile).some((issue) => issue.key === "materials.degree_certificate_status"));
}
{
  assert.equal(STANDARD_PROFILE_MODULE_STEPS.language, 3);
}
{
  const current = completeFixture();
  const draft = structuredClone(current);
  draft.language.IELTS_status = "has_value";
  draft.language.IELTS = 7.5;
  const merged = mergeProfileModule(current, draft, "language");
  assert.equal(merged.language.IELTS, 7.5);
  assert.deepEqual(merged.education.gpa, current.education.gpa);
  assert.deepEqual(merged.standardized_test, current.standardized_test);
  assert.deepEqual(merged.materials, current.materials);
}
{
  const profile = completeFixture();
  profile.education.university = "";
  profile.education.major = "";
  assert.equal(firstMissingProfileStep(profile), 0);
  profile.education.university = "University X";
  assert.equal(firstMissingProfileStep(profile), 1);
}
{
  assert.deepEqual([...STANDARD_PROFILE_STEPS], ["本科院校", "本科专业", "学术成绩", "语言考试", "标化考试", "申请材料", "完整性检查"]);
  assert(!STANDARD_PROFILE_STEPS.some((step) => step.includes("经历")));
  const profile = completeFixture();
  profile.experience.internship_status = null;
  profile.experience.work_status = null;
  profile.experience.research_status = null;
  profile.experience.project_status = null;
  assert.deepEqual(profileCompleteness(profile), []);
}
{
  const profile = completeFixture();
  profile.materials.cv_status = null;
  profile.materials.portfolio_status = null;
  profile.materials.confirmed_recommenders = null;
  const initialCount = profileCompleteness(profile).length;
  profile.materials.cv_status = "prepared";
  assert.equal(profileCompleteness(profile).length, initialCount - 1);
  profile.materials.portfolio_status = "not_prepared";
  assert.equal(profileCompleteness(profile).length, initialCount - 2);
  profile.materials.confirmed_recommenders = 0;
  assert.equal(profileCompleteness(profile).length, initialCount - 3);
}
{
  const profile = completeFixture();
  profile.standardized_test.GRE_status = null;
  assert(profileCompleteness(profile).some((issue) => issue.key === "standardized_test.GRE_status"));
  profile.standardized_test.GRE_status = "none";
  assert(!profileCompleteness(profile).some((issue) => issue.key.includes("GRE")));
}
{
  const profile = completeFixture();
  profile.education.gpa = null;
  profile.education.average_score = null;
  assert(profileCompleteness(profile).some((issue) => issue.key === "education.academic_score"));
  profile.education.average_score = { value: 86, scale: 100 };
  assert(!profileCompleteness(profile).some((issue) => issue.key === "education.academic_score"));
  profile.education.major = "";
  assert(profileCompleteness(profile).some((issue) => issue.key === "education.major"));
}
{
  const css = readFileSync(new URL("../src/app/page.module.css", import.meta.url), "utf8");
  assert(/\.chat\s*\{[^}]*min-height:0[^}]*overflow:hidden/.test(css));
  assert(/\.messages\s*\{[^}]*min-height:0[^}]*overflow-y:auto/.test(css));
  assert(/\.chatHeader\s*\{[^}]*flex:0 0 auto/.test(css));
  assert(/\.profileInterviewActions\s*\{[^}]*flex:0 0 auto/.test(css));
}

console.log("standard profile regressions: PASS");
