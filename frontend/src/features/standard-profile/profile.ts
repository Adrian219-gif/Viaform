export type AnswerStatus = "has_value" | "none" | "unknown" | null;
export type MaterialStatus = "prepared" | "not_prepared" | "unknown" | "not_applicable" | null;

export type ScoreWithScale = { value: number | null; scale: number | null };

export type StandardUserProfile = {
  education: {
    university: string;
    major: string;
    gpa: ScoreWithScale | null;
    average_score: ScoreWithScale | null;
    courses: string[];
  };
  experience: {
    projects: string[];
    research: string[];
    internship: string[];
    work: string[];
    project_status: AnswerStatus;
    research_status: AnswerStatus;
    internship_status: AnswerStatus;
    work_status: AnswerStatus;
  };
  language: {
    IELTS: number | null;
    TOEFL: number | null;
    IELTS_status: AnswerStatus;
    TOEFL_status: AnswerStatus;
    IELTS_subscores: { listening: number | null; reading: number | null; writing: number | null; speaking: number | null };
    TOEFL_subscores: { reading: number | null; listening: number | null; speaking: number | null; writing: number | null };
  };
  standardized_test: {
    GRE: number | null;
    GMAT: number | null;
    GRE_status: AnswerStatus;
    GMAT_status: AnswerStatus;
  };
  materials: {
    cv_status: MaterialStatus;
    transcript_status: MaterialStatus;
    degree_certificate_status: MaterialStatus;
    motivation_letter_status: MaterialStatus;
    portfolio_status: MaterialStatus;
    confirmed_recommenders: number | null;
  };
};

export type ProfileIssue = { key: string; label: string; step: number };

export const STANDARD_PROFILE_STEPS = ["本科院校", "本科专业", "学术成绩", "语言考试", "标化考试", "申请材料", "完整性检查"] as const;

export const EMPTY_STANDARD_PROFILE: StandardUserProfile = {
  education: { university: "", major: "", gpa: null, average_score: null, courses: [] },
  experience: {
    projects: [], research: [], internship: [], work: [],
    project_status: null, research_status: null, internship_status: null, work_status: null,
  },
  language: {
    IELTS: null, TOEFL: null, IELTS_status: null, TOEFL_status: null,
    IELTS_subscores: { listening: null, reading: null, writing: null, speaking: null },
    TOEFL_subscores: { reading: null, listening: null, speaking: null, writing: null },
  },
  standardized_test: { GRE: null, GMAT: null, GRE_status: null, GMAT_status: null },
  materials: {
    cv_status: null, transcript_status: null, degree_certificate_status: null, motivation_letter_status: null,
    portfolio_status: null, confirmed_recommenders: null,
  },
};

export function validScore(score: ScoreWithScale | null): boolean {
  return Boolean(score && score.value !== null && score.scale !== null && score.scale > 0 && score.value >= 0 && score.value <= score.scale);
}

export function academicScoreComplete(profile: StandardUserProfile): boolean {
  return validScore(profile.education.gpa) || validScore(profile.education.average_score);
}

export function profileCompleteness(profile: StandardUserProfile): ProfileIssue[] {
  const issues: ProfileIssue[] = [];
  if (!profile.education.university.trim()) issues.push({ key: "education.university", label: "本科院校", step: 0 });
  if (!profile.education.major.trim()) issues.push({ key: "education.major", label: "本科专业", step: 1 });
  const gpa = profile.education.gpa;
  const average = profile.education.average_score;
  if (gpa && (gpa.value === null || gpa.scale === null || !validScore(gpa))) issues.push({ key: "education.gpa", label: "GPA 数值与分制必须成对填写，且成绩不能高于分制", step: 2 });
  if (average && (average.value === null || average.scale === null || !validScore(average))) issues.push({ key: "education.average_score", label: "平均分数值与满分必须成对填写，且成绩不能高于满分", step: 2 });
  if (!academicScoreComplete(profile)) issues.push({ key: "education.academic_score", label: "学术成绩（GPA 或均分至少填写一种）", step: 2 });
  if (profile.language.IELTS_status === null) issues.push({ key: "language.IELTS_status", label: "IELTS 成绩状态", step: 3 });
  if (profile.language.TOEFL_status === null) issues.push({ key: "language.TOEFL_status", label: "TOEFL 成绩状态", step: 3 });
  if (profile.language.IELTS_status === "has_value" && profile.language.IELTS === null) issues.push({ key: "language.IELTS", label: "IELTS 总分", step: 3 });
  if (profile.language.TOEFL_status === "has_value" && profile.language.TOEFL === null) issues.push({ key: "language.TOEFL", label: "TOEFL 总分", step: 3 });
  if (profile.standardized_test.GRE_status === null) issues.push({ key: "standardized_test.GRE_status", label: "GRE 成绩状态", step: 4 });
  if (profile.standardized_test.GMAT_status === null) issues.push({ key: "standardized_test.GMAT_status", label: "GMAT 成绩状态", step: 4 });
  if (profile.standardized_test.GRE_status === "has_value" && profile.standardized_test.GRE === null) issues.push({ key: "standardized_test.GRE", label: "GRE 成绩", step: 4 });
  if (profile.standardized_test.GMAT_status === "has_value" && profile.standardized_test.GMAT === null) issues.push({ key: "standardized_test.GMAT", label: "GMAT 成绩", step: 4 });
  const materialFields: Array<[keyof StandardUserProfile["materials"], string]> = [
    ["cv_status", "CV / Resume 状态"], ["transcript_status", "成绩单状态"],
    ["degree_certificate_status", "学位证状态"],
    ["motivation_letter_status", "SOP / Personal Statement / Motivation Letter 状态"],
    ["portfolio_status", "作品集状态"],
  ];
  for (const [key, label] of materialFields) {
    if (profile.materials[key] === null) issues.push({ key: `materials.${key}`, label, step: 5 });
  }
  if (profile.materials.confirmed_recommenders === null) issues.push({ key: "materials.confirmed_recommenders", label: "已确认推荐人数量", step: 5 });
  return issues;
}

export function profileHasForbiddenProgrammeSpecificFields(profile: StandardUserProfile): boolean {
  return profile.education.courses.length > 0;
}

export function canProceedToExplore(profile: StandardUserProfile, intent: "complete" | "skip"): boolean {
  return intent === "skip" || profileCompleteness(profile).length === 0;
}

export function firstMissingProfileStep(profile: StandardUserProfile): number | null {
  return profileCompleteness(profile)[0]?.step ?? null;
}
