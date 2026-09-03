"use client";

import { useMemo, useState } from "react";
import styles from "./SpecialRequirementInterview.module.css";
import {
  isCourseItemComplete,
  specialInterviewCompletion,
} from "./completion";

type Availability = "known" | "known_negative" | "unknown";

export type SpecialInterviewCourse = {
  item_id: string;
  prerequisite_kind: "concrete_course" | "course_category";
  canonical_label: string | null;
  category_label: string | null;
  minimum_courses: number | null;
  evidence_key: string;
  suggested_user_courses: string[];
};

export type SpecialInterviewSource = {
  requirement_id: string;
  requirement: string;
  requirement_zh: string | null;
  source_url: string | null;
  verification_status: "official_verified" | "user_supplied";
};

export type SpecialInterviewPlan = {
  authoritative_prerequisite_plan: {
    group_id: string;
    requirement_id: string;
    relation: "all_of" | "one_of";
    items: {
      item_id: string;
      prerequisite_kind: "concrete_course" | "course_category";
      canonical_label: string | null;
      category_label: string | null;
      display_label: string;
      course_code: string | null;
      minimum_courses: number | null;
      evidence_key: string;
    }[];
  }[];
  aggregate_course_credits: {
    item_id: string;
    requirement_id: string;
    label: string;
    required_quantity: number;
    unit: string;
    evidence_key: string;
    source: SpecialInterviewSource;
  }[];
  authoritative_course_credit_plan: {
    item_id: string;
    requirement_id: string;
    label: string;
    required_quantity: number;
    unit: string;
    evidence_key: string;
  }[];
  prerequisite_groups: {
    group_id: string;
    relation: "all_of" | "one_of";
    courses: SpecialInterviewCourse[];
    source: SpecialInterviewSource;
  }[];
  objective_special_requirements: {
    item_id: string;
    canonical_label: string;
    evidence_key: string;
    special_type: string;
    expected_answer_type: "ternary";
    source: SpecialInterviewSource;
  }[];
  reusable_evidence: unknown[];
  trusted_requirement_count: number;
  extracted_item_count: number;
  remaining_item_count: number;
  extraction_llm_requests: number;
};

export type SpecialInterviewSubmission = {
  evidence_key: string;
  item_id?: string | null;
  canonical_label: string;
  item_type: "prerequisite_course" | "objective_special" | "aggregate_course_credit";
  prerequisite_kind?: "concrete_course" | "course_category" | null;
  minimum_courses?: number | null;
  availability: Availability;
  requirement_id: string;
  user_course_name?: string | null;
  user_course_names?: string[];
  quantity?: number | null;
  unit?: string | null;
  required_quantity?: number | null;
};

type Props = {
  university: string;
  program: string;
  plan: SpecialInterviewPlan;
  submitting: boolean;
  error: string;
  onSubmit: (answers: SpecialInterviewSubmission[]) => void;
};

const COURSE_OPTIONS: { value: Availability; label: string }[] = [
  { value: "known", label: "修过" },
  { value: "known_negative", label: "没修过" },
  { value: "unknown", label: "不确定" },
];

const SPECIAL_OPTIONS: { value: Availability; label: string }[] = [
  { value: "known", label: "持有 / 符合" },
  { value: "known_negative", label: "没有" },
  { value: "unknown", label: "不确定" },
];

export default function SpecialRequirementInterview({
  university,
  program,
  plan,
  submitting,
  error,
  onSubmit,
}: Props) {
  const [answers, setAnswers] = useState<Record<string, Availability>>({});
  const [courseNames, setCourseNames] = useState<Record<string, string[]>>({});
  const [aggregateQuantities, setAggregateQuantities] = useState<Record<string, string>>({});
  const [validationError, setValidationError] = useState("");

  const completion = useMemo(
    () => specialInterviewCompletion(plan, answers, courseNames, aggregateQuantities),
    [aggregateQuantities, answers, courseNames, plan],
  );

  function choose(key: string, availability: Availability) {
    setAnswers((current) => ({ ...current, [key]: availability }));
    setValidationError("");
  }

  function submit() {
    if (!completion.canSubmit) {
      setValidationError(completion.validationMessage);
      return;
    }
    const submissions: SpecialInterviewSubmission[] = [];
    plan.prerequisite_groups.forEach((group) => {
      group.courses.forEach((course) => {
        const availability = answers[course.evidence_key];
        if (!availability) return;
        submissions.push({
          evidence_key: course.evidence_key,
          item_id: course.item_id,
          canonical_label: course.canonical_label || course.category_label || "",
          item_type: "prerequisite_course",
          prerequisite_kind: course.prerequisite_kind,
          minimum_courses: course.minimum_courses,
          availability,
          requirement_id: group.source.requirement_id,
          user_course_name: availability === "known" && course.prerequisite_kind === "concrete_course"
            ? courseNames[course.evidence_key]?.[0]?.trim() || null
            : null,
          user_course_names: availability === "known" && course.prerequisite_kind === "course_category"
            ? (courseNames[course.evidence_key] ?? []).map((name) => name.trim()).filter(Boolean)
            : [],
        });
      });
    });
    plan.objective_special_requirements.forEach((item) => {
      const availability = answers[item.evidence_key];
      if (!availability) return;
      submissions.push({
        evidence_key: item.evidence_key,
        canonical_label: item.canonical_label,
        item_type: "objective_special",
        availability,
        requirement_id: item.source.requirement_id,
      });
    });
    plan.aggregate_course_credits.forEach((item) => {
      const availability = answers[item.evidence_key];
      if (availability !== "known" && availability !== "unknown") return;
      submissions.push({
        evidence_key: item.evidence_key,
        item_id: item.item_id,
        canonical_label: item.label,
        item_type: "aggregate_course_credit",
        availability,
        requirement_id: item.requirement_id,
        quantity: availability === "known"
          ? Number(aggregateQuantities[item.evidence_key])
          : null,
        unit: item.unit,
        required_quantity: item.required_quantity,
      });
    });
    onSubmit(submissions);
  }

  return <div className={styles.stage}>
    <header className={styles.header}>
      <p>SPECIAL REQUIREMENT INTERVIEW</p>
      <h1>确认项目特定背景</h1>
      <span>{university} · {program}</span>
      <small>仅收集官网可信 Requirements 中第一轮未覆盖的客观事实；课程等价性仍由你自行确认。</small>
    </header>
    <main className={styles.content}>
      {plan.prerequisite_groups.map((group) => <section className={styles.card} key={group.group_id}>
        <div className={styles.cardHeading}>
          <div><span>前置课程确认</span><h2>{group.relation === "one_of" ? "以下课程满足其中一项即可" : "以下课程要求均需确认"}</h2></div>
        </div>
        <p className={styles.sourceText}>{group.source.requirement_zh || group.source.requirement}</p>
        <div className={styles.items}>{group.courses.map((course) => {
          const label = course.canonical_label || course.category_label || "课程";
          const requiredNames = course.prerequisite_kind === "course_category" ? course.minimum_courses ?? 1 : 1;
          return <article key={course.evidence_key}>
          {course.prerequisite_kind === "course_category" ? <>
            <h3>{label} 类课程</h3>
            <p className={styles.categoryRequirement}>{course.minimum_courses ? `该项目要求至少修过 ${course.minimum_courses} 门 ${label} 类课程。` : `该项目要求具备 ${label} 类课程背景。`}</p>
            <strong>你本科阶段是否修过符合这一类别的课程？</strong>
          </> : <strong>你本科阶段是否修过 {label} 或内容相近的课程？</strong>}
          <div className={styles.options}>{COURSE_OPTIONS.map((option) => <button type="button" key={option.value} className={answers[course.evidence_key] === option.value ? styles.selected : ""} onClick={() => choose(course.evidence_key, option.value)}>{option.label}</button>)}</div>
          {answers[course.evidence_key] === "known" && <div className={styles.courseNameFields}>
            <span>对应的本科课程名称{course.prerequisite_kind === "concrete_course" ? "（可选）" : ""}</span>
            {Array.from({ length: requiredNames }, (_, index) => <input key={index} value={courseNames[course.evidence_key]?.[index] ?? ""} onChange={(event) => {
              const value = event.target.value;
              setValidationError("");
              setCourseNames((current) => {
                const next = [...(current[course.evidence_key] ?? [])];
                next[index] = value;
                return { ...current, [course.evidence_key]: next };
              });
            }} placeholder={requiredNames > 1 ? `课程 ${index + 1}` : course.prerequisite_kind === "course_category" ? "例如：Operating Systems" : "例如：Matrix Algebra"} />)}
            {course.prerequisite_kind === "course_category" && course.suggested_user_courses.length > 0 && <small>你已记录的课程（仅供确认参考，不代表自动满足本类别）：{course.suggested_user_courses.join("、")}</small>}
            <small>如果课程名称与项目要求不同，建议查看本科院校官网课程描述或 syllabus，再确认课程内容是否覆盖。</small>
            {!isCourseItemComplete(course, answers[course.evidence_key], courseNames[course.evidence_key]) && <small className={styles.itemIncomplete}>{requiredNames > 1 ? `还需填写 ${requiredNames - (courseNames[course.evidence_key] ?? []).filter((name) => name.trim()).length} 门课程名称。` : "填写课程名称后，此项才算确认完成。"}</small>}
          </div>}
        </article>})}</div>
      </section>)}
      {plan.aggregate_course_credits.length > 0 && <section className={styles.card}>
        <div className={styles.cardHeading}><div><span>相关课程总学分</span><h2>确认课程学分总量</h2></div></div>
        <div className={styles.items}>{plan.aggregate_course_credits.map((item) => <article key={item.item_id}>
          <strong>满足上述相关课程要求的课程合计多少 {item.unit}？</strong>
          <p className={styles.sourceText}>{item.source.requirement_zh || item.source.requirement}</p>
          <div className={styles.courseNameFields}>
            <input type="number" min="0" step="any" value={aggregateQuantities[item.evidence_key] ?? ""} onChange={(event) => {
              const value = event.target.value;
              setAggregateQuantities((current) => ({ ...current, [item.evidence_key]: value }));
              if (value.trim()) {
                choose(item.evidence_key, "known");
              } else {
                setAnswers((current) => {
                  const next = { ...current };
                  delete next[item.evidence_key];
                  return next;
                });
              }
            }} placeholder={`例如：${item.required_quantity}`} />
            <button type="button" className={answers[item.evidence_key] === "unknown" ? styles.selected : ""} onClick={() => {
              setAggregateQuantities((current) => ({ ...current, [item.evidence_key]: "" }));
              choose(item.evidence_key, "unknown");
            }}>不确定</button>
            {answers[item.evidence_key] !== "unknown" && !aggregateQuantities[item.evidence_key]?.trim() && <small className={styles.itemIncomplete}>填写总 {item.unit}，或选择“不确定”。</small>}
          </div>
        </article>)}</div>
      </section>}
      {plan.objective_special_requirements.length > 0 && <section className={styles.card}>
        <div className={styles.cardHeading}><div><span>客观特殊要求</span><h2>确认其他项目特定事实</h2></div></div>
        <div className={styles.items}>{plan.objective_special_requirements.map((item) => <article key={item.item_id}>
          <strong>{item.special_type.toLowerCase().includes("thesis") ? `你本科阶段是否完成过 ${item.canonical_label}？` : `你目前是否持有或符合 ${item.canonical_label}？`}</strong>
          <div className={styles.options}>{SPECIAL_OPTIONS.map((option) => <button type="button" key={option.value} className={answers[item.evidence_key] === option.value ? styles.selected : ""} onClick={() => choose(item.evidence_key, option.value)}>{option.label}</button>)}</div>
        </article>)}</div>
      </section>}
    </main>
    <footer className={styles.footer}>
      <div><strong>已确认 {completion.completedCount} / {plan.remaining_item_count}</strong><span>不确定会作为独立终态保存，不等同于没有。</span></div>
      <button type="button" onClick={submit} disabled={submitting}>{submitting ? "正在保存…" : "保存并进入 Gap 分析"}</button>
      {(validationError || error) && <p>{validationError || error}</p>}
    </footer>
  </div>;
}
