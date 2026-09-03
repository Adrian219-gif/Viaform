export type SpecialAvailability = "known" | "known_negative" | "unknown";

type CourseItem = {
  evidence_key: string;
  prerequisite_kind: "concrete_course" | "course_category";
  canonical_label: string | null;
  category_label: string | null;
  minimum_courses: number | null;
};

type CompletionPlan = {
  prerequisite_groups: {
    relation: "all_of" | "one_of";
    courses: CourseItem[];
  }[];
  objective_special_requirements: {
    evidence_key: string;
    canonical_label: string;
  }[];
  aggregate_course_credits: {
    evidence_key: string;
    label: string;
    unit: string;
  }[];
};

export type SpecialInterviewCompletion = {
  completedCount: number;
  canSubmit: boolean;
  validationMessage: string;
};

export function cleanedCourseNames(names: string[] | undefined): string[] {
  return (names ?? []).map((name) => name.trim()).filter(Boolean);
}

export function isCourseItemComplete(
  course: CourseItem,
  availability: SpecialAvailability | undefined,
  names: string[] | undefined,
): boolean {
  if (!availability) return false;
  if (course.prerequisite_kind !== "course_category" || availability !== "known") {
    return true;
  }
  return cleanedCourseNames(names).length >= (course.minimum_courses ?? 1);
}

export function isAggregateCreditComplete(
  availability: SpecialAvailability | undefined,
  rawQuantity: string | undefined,
): boolean {
  if (availability === "unknown") return true;
  if (availability !== "known" || rawQuantity === undefined || rawQuantity.trim() === "") {
    return false;
  }
  const quantity = Number(rawQuantity);
  return Number.isFinite(quantity) && quantity >= 0;
}

export function specialInterviewCompletion(
  plan: CompletionPlan,
  answers: Record<string, SpecialAvailability>,
  courseNames: Record<string, string[]>,
  aggregateQuantities: Record<string, string>,
): SpecialInterviewCompletion {
  const courses = plan.prerequisite_groups.flatMap((group) => group.courses);
  const completedCourses = courses.filter((course) =>
    isCourseItemComplete(course, answers[course.evidence_key], courseNames[course.evidence_key]));
  const completedObjectives = plan.objective_special_requirements.filter(
    (item) => Boolean(answers[item.evidence_key]),
  );
  const completedCredits = plan.aggregate_course_credits.filter((item) =>
    isAggregateCreditComplete(
      answers[item.evidence_key],
      aggregateQuantities[item.evidence_key],
    ));

  for (const course of courses) {
    if (course.prerequisite_kind !== "course_category" || answers[course.evidence_key] !== "known") continue;
    const required = course.minimum_courses ?? 1;
    const actual = cleanedCourseNames(courseNames[course.evidence_key]).length;
    if (actual >= required) continue;
    const label = course.category_label || course.canonical_label || "该课程类别";
    const missing = required - actual;
    return {
      completedCount: completedCourses.length + completedObjectives.length + completedCredits.length,
      canSubmit: false,
      validationMessage: required === 1
        ? `请填写「${label}」对应的本科课程名称。`
        : `「${label}」类课程还需要填写 ${missing} 门本科课程名称。`,
    };
  }

  for (const group of plan.prerequisite_groups) {
    const groupComplete = group.relation === "all_of"
      ? group.courses.every((course) => isCourseItemComplete(
        course, answers[course.evidence_key], courseNames[course.evidence_key]))
      : group.courses.some((course) => answers[course.evidence_key] === "known"
          && isCourseItemComplete(course, answers[course.evidence_key], courseNames[course.evidence_key]))
        || group.courses.every((course) => isCourseItemComplete(
          course, answers[course.evidence_key], courseNames[course.evidence_key]));
    if (groupComplete) continue;
    return {
      completedCount: completedCourses.length + completedObjectives.length + completedCredits.length,
      canSubmit: false,
      validationMessage: group.relation === "all_of"
        ? "请确认该课程组中的所有必需项。"
        : "请至少确认其中一项；如果均不符合或不确定，请完成相应选择。",
    };
  }

  const missingObjective = plan.objective_special_requirements.find(
    (item) => !answers[item.evidence_key],
  );
  if (missingObjective) {
    return {
      completedCount: completedCourses.length + completedObjectives.length + completedCredits.length,
      canSubmit: false,
      validationMessage: `请确认「${missingObjective.canonical_label}」。`,
    };
  }

  const missingCredit = plan.aggregate_course_credits.find((item) =>
    !isAggregateCreditComplete(
      answers[item.evidence_key],
      aggregateQuantities[item.evidence_key],
    ));
  if (missingCredit) {
    return {
      completedCount: completedCourses.length + completedObjectives.length + completedCredits.length,
      canSubmit: false,
      validationMessage: `请填写「${missingCredit.label}」的总 ${missingCredit.unit}，或选择“不确定”。`,
    };
  }

  return {
    completedCount: completedCourses.length + completedObjectives.length + completedCredits.length,
    canSubmit: true,
    validationMessage: "",
  };
}
