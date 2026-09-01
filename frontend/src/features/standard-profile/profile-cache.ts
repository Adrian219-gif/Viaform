import { EMPTY_STANDARD_PROFILE } from "./profile.ts";
import type { StandardUserProfile } from "./profile.ts";

export const UNIFIED_PROFILE_CACHE_KEY = "unified_profile_v2";
export type CachedProfileStatus = "not_started" | "completed" | "skipped";
export type StandardProfileCacheRecord = {
  version: 2;
  profile: StandardUserProfile;
  profileStatus: CachedProfileStatus;
  updated_at: string;
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function normalizeCachedProfile(value: unknown): StandardUserProfile {
  const candidate = object(value);
  const education = object(candidate.education);
  const experience = object(candidate.experience);
  const language = object(candidate.language);
  const tests = object(candidate.standardized_test);
  const materials = object(candidate.materials);
  return {
    education: { ...EMPTY_STANDARD_PROFILE.education, ...education } as StandardUserProfile["education"],
    experience: { ...EMPTY_STANDARD_PROFILE.experience, ...experience } as StandardUserProfile["experience"],
    language: {
      ...EMPTY_STANDARD_PROFILE.language,
      ...language,
      IELTS_subscores: { ...EMPTY_STANDARD_PROFILE.language.IELTS_subscores, ...object(language.IELTS_subscores) },
      TOEFL_subscores: { ...EMPTY_STANDARD_PROFILE.language.TOEFL_subscores, ...object(language.TOEFL_subscores) },
    } as StandardUserProfile["language"],
    standardized_test: { ...EMPTY_STANDARD_PROFILE.standardized_test, ...tests } as StandardUserProfile["standardized_test"],
    materials: { ...EMPTY_STANDARD_PROFILE.materials, ...materials } as StandardUserProfile["materials"],
  };
}

export function readStandardProfileCache(storage: StorageLike): StandardProfileCacheRecord | null {
  const raw = storage.getItem(UNIFIED_PROFILE_CACHE_KEY);
  if (!raw) return null;
  try {
    const parsed = object(JSON.parse(raw));
    const hasEnvelope = "profile" in parsed;
    const profile = normalizeCachedProfile(hasEnvelope ? parsed.profile : parsed);
    const status = parsed.profileStatus;
    return {
      version: 2,
      profile,
      profileStatus: status === "completed" || status === "skipped" ? status : "not_started",
      updated_at: typeof parsed.updated_at === "string" ? parsed.updated_at : "",
    };
  } catch {
    return null;
  }
}

export function writeStandardProfileCache(
  storage: StorageLike,
  profile: StandardUserProfile,
  profileStatus: CachedProfileStatus,
  now: string = new Date().toISOString(),
): StandardProfileCacheRecord {
  const existing = readStandardProfileCache(storage);
  const normalized = normalizeCachedProfile(profile);
  const record: StandardProfileCacheRecord = {
    version: 2,
    profile: {
      ...normalized,
      // Historical experience remains intact even though First-round no longer asks it.
      experience: normalized.experience ?? existing?.profile.experience ?? EMPTY_STANDARD_PROFILE.experience,
    },
    profileStatus,
    updated_at: now,
  };
  storage.setItem(UNIFIED_PROFILE_CACHE_KEY, JSON.stringify(record));
  return record;
}

export type StandardProfileModule = "university" | "major" | "academic" | "language" | "standardized" | "materials";
export const STANDARD_PROFILE_MODULE_STEPS: Record<StandardProfileModule, number> = {
  university: 0, major: 1, academic: 2, language: 3, standardized: 4, materials: 5,
};

export function profileEntryView(status: CachedProfileStatus): "summary" | "incomplete" {
  return status === "completed" ? "summary" : "incomplete";
}

export function mergeProfileModule(
  current: StandardUserProfile,
  draft: StandardUserProfile,
  module: StandardProfileModule,
): StandardUserProfile {
  if (module === "university") return { ...current, education: { ...current.education, university: draft.education.university } };
  if (module === "major") return { ...current, education: { ...current.education, major: draft.education.major } };
  if (module === "academic") return { ...current, education: { ...current.education, gpa: draft.education.gpa, average_score: draft.education.average_score } };
  if (module === "language") return { ...current, language: structuredClone(draft.language) };
  if (module === "standardized") return { ...current, standardized_test: structuredClone(draft.standardized_test) };
  return { ...current, materials: structuredClone(draft.materials) };
}
