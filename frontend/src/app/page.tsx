"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styles from "./page.module.css";

const topics = [
  { id: "university", label: "本科院校", question: "你的本科院校是？", hint: "例如：中山大学" },
  { id: "major", label: "本科专业", question: "你的本科专业是？", hint: "例如：软件工程" },
] as const;

type TopicId = typeof topics[number]["id"];
type Answer = { topic: TopicId; question: string; answer: string };
type ProfileStatus = "not_started" | "completed" | "skipped";
type ScoreWithScale = { value: number | null; scale: number | null };
type UserProfile = {
  education: { university: string; major: string; gpa: ScoreWithScale | null; average_score: ScoreWithScale | null; courses: string[] };
  experience: { projects: string[]; research: string[]; internship: string[] };
  language: { IELTS: number | null; TOEFL: number | null };
  standardized_test: { GRE: number | null; GMAT: number | null };
};
type ExploreTarget = {
  mode: "explore";
  countries: string[];
  target_major: string;
  ranking: { type: "QS"; basis: "overall" | "subject"; min: number | null; max: number | null };
  ranking_subject: string | null;
  additional_preferences: string;
};
type CandidateProgram = {
  university: string;
  program: string;
  country: string;
  ranking: number | null;
  ranking_system: "QS";
  ranking_edition: number;
  ranking_source_url: string;
  official_program_url: string;
  degree_type: string;
  relevance_reason: string;
};
type TargetProgram = {
  university: string;
  program: string;
  official_program_url: string;
  official_domain: string;
  confirmation_status: "confirmed";
  intended_entry_year: number;
  intended_entry_term: "fall" | "spring" | "summer" | "winter";
};
type ApplicationDeadline = { label: string; type: string; date: string; source_url: string };
type ApplicationTimeline = {
  admission_cycle: string;
  application_open_date: string | null;
  application_open_source_url: string | null;
  application_deadlines: ApplicationDeadline[];
  rolling_admission: boolean | null;
  rolling_admission_source_url: string | null;
  status: "complete" | "partial" | "not_found";
};
type RequirementCategory = "academic" | "course" | "language" | "standardized_test" | "experience" | "materials" | "other";
type RequirementCoverage = "official_verified" | "model_memory_unverified" | "user_supplied" | "not_found";
type RequirementTemporalApplicability = "target_cycle_confirmed" | "undated" | "previous_cycle" | "not_yet_published" | "unknown";
type RequirementItem = {
  category: RequirementCategory;
  requirement: string;
  requirement_zh?: string | null;
  importance: "required" | "recommended" | "preferred" | "unknown";
  source_level: "program" | "department" | "university" | "unknown";
  source_type: "official_retrieval" | "model_memory" | "user_supplied";
  verification_status: "official_verified" | "model_memory_unverified" | "user_supplied";
  source_url: string | null;
  source_cycle: string | null;
  temporal_applicability: RequirementTemporalApplicability;
  temporal_note: string | null;
};
type RequirementCategoryReview = { category: RequirementCategory; coverage: RequirementCoverage; requirements: RequirementItem[] };
type TargetProgramRequirementsReview = { target_program: TargetProgram; checked_at: string; categories: RequirementCategoryReview[] };
type EvidenceAvailability = "known" | "known_negative" | "unknown";
type GapStatus = "met" | "partial" | "not_met" | "unknown";
type GapEvidenceType = "education_university" | "education_major" | "academic_score" | "language_score" | "standardized_score" | "courses" | "material_status" | "material_quantity" | "experience" | "generic";
type UserEvidence = { evidence_type: GapEvidenceType; key: string; value: unknown; raw_answer: string; availability: EvidenceAvailability; updated_at: string; source_requirement_ids: string[] };
type GapEvidenceNeed = { key: string; evidence_type: GapEvidenceType; label: string; already_known: boolean; required_fields: string[]; evidence_group: string | null; group_relation: "all" | "any"; minimum: number | null; component_minimum: number | null; required_quantity: number | null };
type GapQuestion = { question_id: string; question: string; evidence_keys: string[] };
type GapPlannedRequirement = {
  requirement_id: string;
  category: RequirementCategory;
  requirement: string;
  requirement_zh?: string | null;
  importance: RequirementItem["importance"];
  requirement_verification_status: "official_verified" | "model_memory_unverified" | "user_supplied";
  source_url: string | null;
  source_cycle: string | null;
  temporal_applicability: RequirementTemporalApplicability;
  temporal_note: string | null;
  matchable: boolean;
  informational_reason: string;
  match_strategy: "deterministic" | "semantic" | "hybrid";
  evidence_needs: GapEvidenceNeed[];
  constraint: { kind: string; options: unknown[] };
};
type GapPlan = { target_program: TargetProgram; requirements: GapPlannedRequirement[]; questions: GapQuestion[]; reusable_evidence: UserEvidence[]; planning_llm_requests: number };
type GapResult = { requirement_id: string; category: RequirementCategory; requirement: string; requirement_zh?: string | null; requirement_verification_status: "official_verified" | "model_memory_unverified" | "user_supplied"; importance: RequirementItem["importance"]; status: GapStatus; user_evidence: string; gap: string; reason: string; source_url: string | null; source_cycle: string | null; temporal_applicability: RequirementTemporalApplicability; temporal_note: string | null };
type GapAnalysisResponse = { target_program: TargetProgram; results: GapResult[]; informational_requirements: GapPlannedRequirement[]; semantic_llm_requests: number };
type PlanningAction = {
  action_id: string;
  action: string;
  action_kind: "complete_gap" | "resolve_gap" | "confirm_information";
  time_period: string;
  target_date: string | null;
  priority: "high" | "medium" | "optional";
  requirement_type: RequirementItem["importance"];
  plan_track: "main" | "optional";
  source_gap_id: string;
  reason: string;
  status: "pending" | "in_progress" | "completed" | "blocked";
  depends_on: string[];
  parallel_group: string | null;
};
type ActionPlan = {
  target_program: TargetProgram;
  generated_at: string;
  current_date: string;
  timeline_status: ApplicationTimeline["status"];
  application_deadline: string | null;
  application_deadline_label: string | null;
  deadline_is_precise: boolean;
  ready_by_date: string | null;
  actions: PlanningAction[];
  planning_llm_requests: number;
};
type OverallRanking = { edition: number; rank_display: string; rank_min: number; rank_max: number | null };
type SubjectRanking = OverallRanking & { subject: string };
type CandidateUniversity = {
  university: string;
  country: string;
  ranking: number;
  rank_display: string;
  rank_min: number;
  rank_max: number | null;
  ranking_system: "QS";
  ranking_basis: "overall" | "subject";
  ranking_subject: string | null;
  ranking_edition: number;
  ranking_source_url: string;
  overall_ranking: OverallRanking | null;
  overall_ranking_status: "ranked" | "not_ranked" | "unknown";
  subject_ranking: SubjectRanking | null;
  school_official_url: string | null;
};
type SubjectMappingResponse = { target_major: string; candidates: string[] };

const COUNTRY_OPTIONS = ["美国", "英国", "中国香港", "新加坡", "澳大利亚", "加拿大", "德国", "欧洲其他地区"];
const REQUIREMENT_CATEGORIES: { id: RequirementCategory; label: string }[] = [
  { id: "academic", label: "学术背景" },
  { id: "course", label: "先修课程" },
  { id: "language", label: "语言要求" },
  { id: "standardized_test", label: "标化考试" },
  { id: "experience", label: "经历要求" },
  { id: "materials", label: "申请材料" },
  { id: "other", label: "其他要求" },
];
const COVERAGE_LABELS: Record<RequirementCoverage, string> = {
  official_verified: "AI 检索自官网",
  model_memory_unverified: "AI 参考 · 当前未确认官方来源",
  user_supplied: "用户补充",
  not_found: "暂未获得明确要求",
};
const IMPORTANCE_LABELS: Record<RequirementItem["importance"], string> = {
  required: "必须",
  recommended: "建议",
  preferred: "优先",
  unknown: "未明确",
};
const SOURCE_LEVEL_LABELS: Record<RequirementItem["source_level"], string> = {
  program: "项目级",
  department: "院系级",
  university: "学校级",
  unknown: "信息层级未确认",
};
const TEMPORAL_APPLICABILITY_LABELS: Record<RequirementTemporalApplicability, string> = {
  target_cycle_confirmed: "目标周期已确认",
  undated: "官网未标周期",
  previous_cycle: "上一周期参考",
  not_yet_published: "目标周期尚未发布",
  unknown: "周期适用性待确认",
};

const EMPTY_PROFILE: UserProfile = {
  education: { university: "", major: "", gpa: null, average_score: null, courses: [] },
  experience: { projects: [], research: [], internship: [] },
  language: { IELTS: null, TOEFL: null },
  standardized_test: { GRE: null, GMAT: null },
};
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_ENTRY_YEAR = new Date().getUTCFullYear() + 1;
const TARGET_CONFIRMATION_TIMEOUT_MS = 35_000;
const REQUIREMENTS_RETRIEVAL_TIMEOUT_MS = 130_000;
const TIMELINE_RETRIEVAL_TIMEOUT_MS = 130_000;
const OVERALL_RANKING_EXPLANATION = "QS 综合排名与学科排名的覆盖范围不同。部分专业型院校可能未进入综合榜，但仍会出现在对应学科排名中。建议结合学科排名判断该校在目标领域的实力。";

function groupPlanningActions(actions: PlanningAction[]) {
  const groups = new Map<string, PlanningAction[]>();
  actions.forEach((action) => {
    const group = groups.get(action.time_period) ?? [];
    group.push(action);
    groups.set(action.time_period, group);
  });
  return Array.from(groups, ([timePeriod, items]) => ({
    timePeriod,
    items: [...items].sort((left, right) => Number(left.plan_track === "optional") - Number(right.plan_track === "optional")),
  }));
}

function planningDisplayText(value: string, hasPreciseDeadline: boolean) {
  if (hasPreciseDeadline) return value;
  return value
    .replace(/正式提交申请|提交申请|递交申请/g, "准备至可提交状态")
    .replace(/submit(?: the)? application/gi, "prepare until ready for submission")
    .replace(/application submission/gi, "ready for submission");
}

function OverallRankingValue({ university }: { university: CandidateUniversity }) {
  if (university.overall_ranking) return <>#{university.overall_ranking.rank_display}</>;
  if (university.overall_ranking_status === "not_ranked") {
    return <span className={styles.rankingStatus}>未进入综合排名 <span className={styles.rankingInfo} tabIndex={0} title={OVERALL_RANKING_EXPLANATION} aria-label={OVERALL_RANKING_EXPLANATION}>ⓘ</span></span>;
  }
  return <span className={styles.rankingStatus}>暂无法确认</span>;
}

export default function Home() {
  const [turns, setTurns] = useState<Answer[]>([]);
  const [profile, setProfile] = useState<UserProfile>(EMPTY_PROFILE);
  const [topicIndex, setTopicIndex] = useState(0);
  const [currentQuestion, setCurrentQuestion] = useState<string>(topics[0].question);
  const [input, setInput] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState<ProfileStatus>("not_started");
  const [errorMessage, setErrorMessage] = useState("");
  const [targetStep, setTargetStep] = useState<"explore" | "entry_cycle" | "requirements" | "gap_interview" | "gap_results" | "planning" | null>(null);
  const [target, setTarget] = useState<ExploreTarget | null>(null);
  const [countries, setCountries] = useState<string[]>([]);
  const [targetMajor, setTargetMajor] = useState("");
  const [rankingBasis, setRankingBasis] = useState<"overall" | "subject">("overall");
  const [subjectCandidates, setSubjectCandidates] = useState<string[]>([]);
  const [selectedSubject, setSelectedSubject] = useState("");
  const [isMappingSubject, setIsMappingSubject] = useState(false);
  const [subjectMappingError, setSubjectMappingError] = useState("");
  const [rankingMin, setRankingMin] = useState("1");
  const [rankingMax, setRankingMax] = useState("100");
  const [intendedEntryYear, setIntendedEntryYear] = useState(String(DEFAULT_ENTRY_YEAR));
  const [intendedEntryTerm, setIntendedEntryTerm] = useState<"fall" | "spring" | "summer" | "winter">("fall");
  const [additionalPreferences, setAdditionalPreferences] = useState("");
  const [candidateUniversities, setCandidateUniversities] = useState<CandidateUniversity[]>([]);
  const [programsByUniversity, setProgramsByUniversity] = useState<Record<string, CandidateProgram[]>>({});
  const [programErrors, setProgramErrors] = useState<Record<string, string>>({});
  const [loadingUniversity, setLoadingUniversity] = useState<string | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [pendingTargetProgram, setPendingTargetProgram] = useState<TargetProgram | null>(null);
  const [activeTargetProgram, setActiveTargetProgram] = useState<TargetProgram | null>(null);
  const [isConfirmingTarget, setIsConfirmingTarget] = useState(false);
  const [confirmationError, setConfirmationError] = useState("");
  const [confirmationUniversity, setConfirmationUniversity] = useState("");
  const [manualUniversity, setManualUniversity] = useState<string | null>(null);
  const [manualProgramUrl, setManualProgramUrl] = useState("");
  const [manualVerifiedProgram, setManualVerifiedProgram] = useState<TargetProgram | null>(null);
  const [requirementsReview, setRequirementsReview] = useState<TargetProgramRequirementsReview | null>(null);
  const [isLoadingRequirements, setIsLoadingRequirements] = useState(false);
  const [requirementsError, setRequirementsError] = useState("");
  const [applicationTimeline, setApplicationTimeline] = useState<ApplicationTimeline | null>(null);
  const [isLoadingTimeline, setIsLoadingTimeline] = useState(false);
  const [timelineError, setTimelineError] = useState("");
  const [supplementCategory, setSupplementCategory] = useState<RequirementCategory | null>(null);
  const [supplementRequirement, setSupplementRequirement] = useState("");
  const [supplementSourceUrl, setSupplementSourceUrl] = useState("");
  const [userEvidence, setUserEvidence] = useState<UserEvidence[]>([]);
  const [gapPlan, setGapPlan] = useState<GapPlan | null>(null);
  const [gapQuestionIndex, setGapQuestionIndex] = useState(0);
  const [gapFollowUpQuestion, setGapFollowUpQuestion] = useState("");
  const [gapFollowUpSlots, setGapFollowUpSlots] = useState<string[]>([]);
  const [satisfiedEvidenceGroups, setSatisfiedEvidenceGroups] = useState<string[]>([]);
  const [gapTurns, setGapTurns] = useState<{ question: string; answer: string }[]>([]);
  const [gapInput, setGapInput] = useState("");
  const [isPlanningGap, setIsPlanningGap] = useState(false);
  const [isParsingGapAnswer, setIsParsingGapAnswer] = useState(false);
  const [isAnalyzingGap, setIsAnalyzingGap] = useState(false);
  const [gapError, setGapError] = useState("");
  const [gapAnalysis, setGapAnalysis] = useState<GapAnalysisResponse | null>(null);
  const [actionPlan, setActionPlan] = useState<ActionPlan | null>(null);
  const [isPlanningActions, setIsPlanningActions] = useState(false);
  const [actionPlanError, setActionPlanError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const discoveryRequestRef = useRef(0);
  const currentTopic = topics[topicIndex];
  const progress = showProfile ? 100 : Math.round((topicIndex / topics.length) * 100);
  const messages = useMemo(() => turns.flatMap((item) => [
    { role: "assistant" as const, content: item.question },
    { role: "user" as const, content: item.answer },
  ]), [turns]);

  function submitAnswer(value: string) {
    const answer = value.trim();
    if (!answer || isProcessing || showProfile) return;

    const turn: Answer = { topic: currentTopic.id, question: currentQuestion, answer };
    const nextTurns = [...turns, turn];
    setTurns(nextTurns);
    setInput("");
    setErrorMessage("");
    setIsProcessing(true);
    setProfile((current) => ({
      ...current,
      education: {
        ...current.education,
        [currentTopic.id]: answer,
      },
    }));
    if (topicIndex === topics.length - 1) {
      setProfileStatus("completed");
      setShowProfile(true);
      setTargetStep("explore");
    } else {
      const nextIndex = topicIndex + 1;
      setTopicIndex(nextIndex);
      setCurrentQuestion(topics[nextIndex].question);
    }
    setIsProcessing(false);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); submitAnswer(input); }
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitAnswer(input); }
  }
  function skipProfile() {
    setProfileStatus("skipped");
    setShowProfile(true);
    setTargetStep("explore");
  }

  function returnToProfile() {
    setTargetStep(null);
    setShowProfile(false);
    setTurns([]);
    setTopicIndex(0);
    setCurrentQuestion(topics[0].question);
    setInput("");
  }

  function toggleCountry(country: string) {
    setCountries((current) => current.includes(country) ? current.filter((item) => item !== country) : [...current, country]);
  }

  function setActiveTarget(targetProgram: TargetProgram) {
    setActiveTargetProgram(targetProgram);
    setTargetStep("requirements");
    setRequirementsReview(null);
    setRequirementsError("");
    setApplicationTimeline(null);
    setTimelineError("");
    setSupplementCategory(null);
    setGapPlan(null);
    setGapQuestionIndex(0);
    setGapFollowUpQuestion("");
    setGapFollowUpSlots([]);
    setSatisfiedEvidenceGroups([]);
    setGapTurns([]);
    setGapInput("");
    setGapAnalysis(null);
    setGapError("");
    setActionPlan(null);
    setActionPlanError("");
    void retrieveRequirements(targetProgram);
    void retrieveTimeline(targetProgram);
  }

  function beginEntryCycleSelection(targetProgram: TargetProgram) {
    setPendingTargetProgram(targetProgram);
    setTargetStep("entry_cycle");
  }

  function confirmEntryCycle() {
    if (!pendingTargetProgram) return;
    const entryYear = Number(intendedEntryYear);
    if (!entryYear) return;
    setActiveTarget({
      ...pendingTargetProgram,
      intended_entry_year: entryYear,
      intended_entry_term: intendedEntryTerm,
    });
    setPendingTargetProgram(null);
  }

  async function retrieveRequirements(targetProgram: TargetProgram) {
    if (isLoadingRequirements) return;
    setIsLoadingRequirements(true);
    setRequirementsError("");
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      REQUIREMENTS_RETRIEVAL_TIMEOUT_MS,
    );
    try {
      const response = await fetch(`${API_BASE_URL}/target-programs/requirements`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(targetProgram),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法分析申请要求。");
      setRequirementsReview(data as TargetProgramRequirementsReview);
    } catch (error) {
      setRequirementsError(
        error instanceof DOMException && error.name === "AbortError"
          ? "项目要求获取超时，请重试。"
          : error instanceof Error
            ? error.message
            : "暂时无法分析申请要求。",
      );
    } finally {
      window.clearTimeout(timeoutId);
      setIsLoadingRequirements(false);
    }
  }

  async function retrieveTimeline(targetProgram: TargetProgram) {
    if (isLoadingTimeline) return;
    setIsLoadingTimeline(true);
    setTimelineError("");
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), TIMELINE_RETRIEVAL_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE_URL}/target-programs/timeline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          university: targetProgram.university,
          program_name: targetProgram.program,
          official_program_url: targetProgram.official_program_url || null,
          intended_entry_year: targetProgram.intended_entry_year,
          intended_entry_term: targetProgram.intended_entry_term,
        }),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法获取申请时间线。");
      setApplicationTimeline(data as ApplicationTimeline);
    } catch (error) {
      setTimelineError(
        error instanceof DOMException && error.name === "AbortError"
          ? "申请时间线获取超时，请重试。"
          : error instanceof Error
            ? error.message
            : "暂时无法获取申请时间线。",
      );
    } finally {
      window.clearTimeout(timeoutId);
      setIsLoadingTimeline(false);
    }
  }

  function saveRequirementSupplement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supplementCategory || !supplementRequirement.trim()) return;
    const userRequirement: RequirementItem = {
      category: supplementCategory,
      requirement: supplementRequirement.trim(),
      requirement_zh: null,
      importance: "unknown",
      source_level: "unknown",
      source_type: "user_supplied",
      verification_status: "user_supplied",
      source_url: supplementSourceUrl.trim() || null,
      source_cycle: null,
      temporal_applicability: "undated",
      temporal_note: null,
    };
    setRequirementsReview((current) => current ? {
      ...current,
      categories: current.categories.map((category) => category.category === supplementCategory ? {
        ...category,
        coverage: "user_supplied",
        requirements: [userRequirement],
      } : category),
    } : current);
    setSupplementCategory(null);
    setSupplementRequirement("");
    setSupplementSourceUrl("");
  }

  function mergeEvidence(current: UserEvidence[], incoming: UserEvidence[]) {
    const merged = new Map(current.map((item) => [item.key.toLowerCase(), item]));
    incoming.forEach((item) => merged.set(item.key.toLowerCase(), item));
    return Array.from(merged.values());
  }

  async function analyzeGap(plan: GapPlan, evidence: UserEvidence[]) {
    if (!activeTargetProgram || isAnalyzingGap) return;
    setIsAnalyzingGap(true);
    setGapError("");
    try {
      const response = await fetch(`${API_BASE_URL}/gap/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_program: activeTargetProgram,
          plan,
          user_profile: profile,
          user_evidence: evidence,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法完成匹配分析。");
      setGapAnalysis(data as GapAnalysisResponse);
      setTargetStep("gap_results");
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法完成匹配分析。");
    } finally {
      setIsAnalyzingGap(false);
    }
  }

  async function startGapInterview() {
    if (!activeTargetProgram || !requirementsReview || isPlanningGap) return;
    setIsPlanningGap(true);
    setGapError("");
    setGapAnalysis(null);
    setGapTurns([]);
    setGapQuestionIndex(0);
    setGapFollowUpQuestion("");
    setGapFollowUpSlots([]);
    setSatisfiedEvidenceGroups([]);
    try {
      const response = await fetch(`${API_BASE_URL}/gap/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_program: activeTargetProgram,
          requirements_review: requirementsReview,
          user_profile: profile,
          user_evidence: userEvidence,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法规划匹配访谈。");
      const plan = data as GapPlan;
      setGapPlan(plan);
      setTargetStep("gap_interview");
      if (plan.questions.length === 0) await analyzeGap(plan, userEvidence);
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法规划匹配访谈。");
    } finally {
      setIsPlanningGap(false);
    }
  }

  async function generateActionPlan() {
    if (!activeTargetProgram || !gapAnalysis || isPlanningActions) return;
    setIsPlanningActions(true);
    setActionPlanError("");
    const timeline = applicationTimeline ?? {
      admission_cycle: `${activeTargetProgram.intended_entry_term} ${activeTargetProgram.intended_entry_year}`,
      application_open_date: null,
      application_open_source_url: null,
      application_deadlines: [],
      rolling_admission: null,
      rolling_admission_source_url: null,
      status: "not_found" as const,
    };
    try {
      const response = await fetch(`${API_BASE_URL}/planning/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_program: activeTargetProgram,
          gap_analysis: gapAnalysis,
          application_timeline: timeline,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法生成申请行动计划。");
      setActionPlan(data as ActionPlan);
      setTargetStep("planning");
    } catch (error) {
      setActionPlanError(error instanceof Error ? error.message : "暂时无法生成申请行动计划。");
    } finally {
      setIsPlanningActions(false);
    }
  }

  async function submitGapAnswer(value: string) {
    const answer = value.trim();
    const question = gapPlan?.questions[gapQuestionIndex];
    if (!answer || !question || !gapPlan || isParsingGapAnswer) return;
    const allNeeds = gapPlan.requirements
      .flatMap((item) => item.evidence_needs)
      .filter((need, index, all) => all.findIndex((item) => item.key === need.key) === index);
    const activeEvidenceKeys = gapFollowUpSlots.length > 0
      ? allNeeds.filter((need) => gapFollowUpSlots.some((slot) => slot.startsWith(`${need.key}.`))).map((need) => need.key)
      : question.evidence_keys;
    const needs = allNeeds.filter((need) => activeEvidenceKeys.includes(need.key));
    setIsParsingGapAnswer(true);
    setGapError("");
    try {
      const displayedQuestion = gapFollowUpQuestion || question.question;
      const response = await fetch(`${API_BASE_URL}/gap/evidence/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: { ...question, question: displayedQuestion, evidence_keys: activeEvidenceKeys },
          evidence_needs: needs,
          existing_evidence: userEvidence,
          answer,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法记录这条回答。");
      const parsed = data as { evidence: UserEvidence[]; missing_slots: string[]; follow_up_question: string | null; satisfied_evidence_groups: string[] };
      const nextEvidence = mergeEvidence(userEvidence, parsed.evidence);
      const nextSatisfiedGroups = Array.from(new Set([...satisfiedEvidenceGroups, ...parsed.satisfied_evidence_groups]));
      setUserEvidence(nextEvidence);
      setSatisfiedEvidenceGroups(nextSatisfiedGroups);
      setGapTurns((current) => [...current, { question: displayedQuestion, answer }]);
      setGapInput("");
      if (parsed.missing_slots.length > 0 && parsed.follow_up_question) {
        setGapFollowUpQuestion(parsed.follow_up_question);
        setGapFollowUpSlots(parsed.missing_slots);
        return;
      }
      setGapFollowUpQuestion("");
      setGapFollowUpSlots([]);
      const evidenceByKey = new Map(nextEvidence.map((item) => [item.key.toLowerCase(), item]));
      const nextQuestionIndex = gapPlan.questions.findIndex((candidate, index) => index > gapQuestionIndex && candidate.evidence_keys.some((key) => {
        const need = allNeeds.find((item) => item.key === key);
        return need && !evidenceByKey.has(key.toLowerCase()) && (!need.evidence_group || !nextSatisfiedGroups.includes(need.evidence_group));
      }));
      if (nextQuestionIndex < 0) {
        await analyzeGap(gapPlan, nextEvidence);
      } else {
        setGapQuestionIndex(nextQuestionIndex);
      }
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法记录这条回答。");
    } finally {
      setIsParsingGapAnswer(false);
    }
  }

  async function requestTargetProgramConfirmation(
    inputTarget: { university: string; program?: string; official_program_url?: string },
  ): Promise<TargetProgram | null> {
    if (isConfirmingTarget) return null;
    setIsConfirmingTarget(true);
    setConfirmationError("");
    setConfirmationUniversity(inputTarget.university.trim());
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      TARGET_CONFIRMATION_TIMEOUT_MS,
    );
    try {
      const response = await fetch(`${API_BASE_URL}/target-programs/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          university: inputTarget.university.trim(),
          program: inputTarget.program?.trim() ?? "",
          official_program_url: inputTarget.official_program_url?.trim() ?? "",
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "AI Web Search 暂时无法识别该项目。");
      return data as TargetProgram;
    } catch (error) {
      setConfirmationError(
        error instanceof DOMException && error.name === "AbortError"
          ? "项目确认超时，请重试。"
          : error instanceof Error
            ? error.message
            : "AI Web Search 暂时无法识别该项目，请检查名称或链接后重试。",
      );
      return null;
    } finally {
      window.clearTimeout(timeoutId);
      setIsConfirmingTarget(false);
    }
  }

  async function confirmTargetProgram(
    inputTarget: { university: string; program: string; official_program_url?: string },
  ) {
    const confirmed = await requestTargetProgramConfirmation(inputTarget);
    if (confirmed) beginEntryCycleSelection(confirmed);
  }

  async function verifyManualProgramUrl(university: string) {
    const confirmed = await requestTargetProgramConfirmation({
      university,
      official_program_url: manualProgramUrl,
    });
    if (confirmed) setManualVerifiedProgram(confirmed);
  }

  const discoverUniversities = useCallback(async (scope: ExploreTarget) => {
    const requestId = ++discoveryRequestRef.current;
    setIsDiscovering(true);
    setDiscoveryError("");
    setCandidateUniversities([]);
    setProgramsByUniversity({});
    setProgramErrors({});
    try {
      const response = await fetch(`${API_BASE_URL}/candidate-universities/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scope),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "候选院校检索失败");
      if (requestId !== discoveryRequestRef.current) return;
      setCandidateUniversities((data as { universities: CandidateUniversity[] }).universities);
    } catch (error) {
      if (requestId !== discoveryRequestRef.current) return;
      setDiscoveryError(error instanceof Error ? error.message : "候选院校检索失败");
    } finally {
      if (requestId === discoveryRequestRef.current) setIsDiscovering(false);
    }
  }, []);

  async function mapQsSubject() {
    const major = targetMajor.trim();
    if (!major || isMappingSubject) return;
    setIsMappingSubject(true);
    setSubjectMappingError("");
    setSubjectCandidates([]);
    setSelectedSubject("");
    try {
      const response = await fetch(`${API_BASE_URL}/rankings/qs/map-subject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_major: major }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "QS 学科匹配失败");
      setSubjectCandidates((data as SubjectMappingResponse).candidates);
    } catch (error) {
      setSubjectMappingError(error instanceof Error ? error.message : "QS 学科匹配失败");
    } finally {
      setIsMappingSubject(false);
    }
  }

  async function discoverPrograms(scope: ExploreTarget, candidateUniversity: CandidateUniversity) {
    const key = candidateUniversity.university;
    if (loadingUniversity) return;
    if (programsByUniversity[key]) {
      setProgramsByUniversity((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      return;
    }

    setLoadingUniversity(key);
    setProgramErrors((current) => ({ ...current, [key]: "" }));
    try {
      const response = await fetch(`${API_BASE_URL}/candidate-programs/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: scope, university: candidateUniversity }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "相关项目检索失败");
      setProgramsByUniversity((current) => ({ ...current, [key]: (data as { candidates: CandidateProgram[] }).candidates }));
    } catch (error) {
      setProgramErrors((current) => ({ ...current, [key]: error instanceof Error ? error.message : "相关项目检索失败" }));
    } finally {
      setLoadingUniversity(null);
    }
  }

  useEffect(() => {
    if (targetStep !== "explore") return;
    const minimum = Number(rankingMin);
    const maximum = Number(rankingMax);
    if (!minimum || !maximum || minimum > maximum) return;
    if (rankingBasis === "subject" && !selectedSubject) {
      setCandidateUniversities([]);
      return;
    }

    const nextTarget: ExploreTarget = {
      mode: "explore",
      countries,
      target_major: targetMajor.trim(),
      ranking: { type: "QS", basis: rankingBasis, min: minimum, max: maximum },
      ranking_subject: rankingBasis === "subject" ? selectedSubject : null,
      additional_preferences: additionalPreferences.trim(),
    };
    const timer = window.setTimeout(() => {
      setTarget(nextTarget);
      void discoverUniversities(nextTarget);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [additionalPreferences, countries, discoverUniversities, rankingBasis, rankingMax, rankingMin, selectedSubject, targetMajor, targetStep]);

  if (showProfile && targetStep) {
    return (
      <main className={`${styles.page} ${styles.targetPage}`}>
        <header className={styles.header}><div className={styles.brand}><span className={styles.brandMark}>知</span><span>知途留学</span></div><span className={styles.status}>{targetStep === "planning" ? "06 · Planning Workflow" : targetStep === "gap_results" ? "05 · Gap Table" : targetStep === "gap_interview" ? "04 · 补充匹配信息" : targetStep === "requirements" ? "03 · 申请要求分析" : targetStep === "entry_cycle" ? "02 · 目标申请周期" : "02 · 目标院校与申请范围"}</span></header>
        <section className={styles.targetShell}>
          <div className={styles.moduleProgress}><span className={profileStatus === "completed" ? styles.moduleDone : styles.moduleSkipped}>{profileStatus === "completed" ? "✓ 基础信息" : "基础信息已跳过"}</span><i /><span className={targetStep === "explore" || targetStep === "entry_cycle" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "explore" ? "2 目标范围" : targetStep === "entry_cycle" ? "2 申请周期" : "✓ 目标项目"}</span>{targetStep !== "explore" && targetStep !== "entry_cycle" && <><i /><span className={targetStep === "requirements" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "requirements" ? "3 要求确认" : "✓ 要求确认"}</span></>}{(targetStep === "gap_interview" || targetStep === "gap_results" || targetStep === "planning") && <><i /><span className={targetStep === "gap_interview" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "gap_interview" ? "4 补充匹配信息" : "✓ 匹配信息"}</span></>}{(targetStep === "gap_results" || targetStep === "planning") && <><i /><span className={targetStep === "gap_results" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "gap_results" ? "5 Gap Table" : "✓ Gap Table"}</span></>}{targetStep === "planning" && <><i /><span className={styles.moduleCurrent}>6 行动计划</span></>}</div>

          {targetStep === "explore" && <>
            <button type="button" className={styles.backButton} onClick={returnToProfile}>← {profileStatus === "completed" ? "返回基础信息" : "补充基础信息"}</button>
            <div className={styles.exploreHeading}><div><p className={styles.eyebrow}>GLOBAL UNIVERSITY EXPLORER</p><h1>探索目标院校</h1></div><p>筛选条件变化后院校会实时更新；相关项目仅在你点击院校后检索。</p></div>
            <div className={styles.exploreWorkspace}>
              <section className={`${styles.targetForm} ${styles.exploreFilters}`}>
                <fieldset><legend>目标国家 / 地区 <small>可多选</small></legend><div className={styles.chipGrid}>{COUNTRY_OPTIONS.map((country) => <button key={country} type="button" className={countries.includes(country) ? styles.selectedChip : ""} onClick={() => toggleCountry(country)}>{countries.includes(country) ? "✓ " : "+ "}{country}</button>)}</div>{!countries.length && <span className={styles.fieldHint}>未选择时显示全球院校</span>}</fieldset>
                <div className={styles.filterRow}><label><span>目标专业</span><input value={targetMajor} onChange={(event) => { setTargetMajor(event.target.value); setSubjectCandidates([]); setSelectedSubject(""); setSubjectMappingError(""); setCandidateUniversities([]); }} placeholder="例如：人工智能、计算机科学" /></label><label><span>榜单类型</span><input value="QS World University Rankings" readOnly aria-readonly="true" /></label></div>
                <fieldset className={styles.rankingBasis}><legend>QS 排名依据</legend><div><button type="button" className={rankingBasis === "overall" ? styles.selectedBasis : ""} onClick={() => { setRankingBasis("overall"); setCandidateUniversities([]); setDiscoveryError(""); }}><strong>按学校综合排名筛选</strong><span>QS World University Rankings · 2027</span><small>看整所大学的综合实力</small></button><button type="button" className={rankingBasis === "subject" ? styles.selectedBasis : ""} onClick={() => { setRankingBasis("subject"); setCandidateUniversities([]); setDiscoveryError(""); }}><strong>按目标学科排名筛选</strong><span>QS World University Rankings by Subject · 2026</span><small>看目标专业对应学科的实力</small></button></div>{rankingBasis === "subject" && selectedSubject && <p className={styles.currentRankingSubject}><span>当前 QS Subject</span><strong>{selectedSubject}</strong></p>}</fieldset>
                {rankingBasis === "subject" && <div className={styles.subjectMapper}>
                  <div><span>目标专业 → QS Subject</span><p>由 DeepSeek 仅从本地 60 个官方 Subject 中推荐；确认后筛选只查询本地数据库。</p></div>
                  <button type="button" onClick={() => void mapQsSubject()} disabled={!targetMajor.trim() || isMappingSubject}>{isMappingSubject ? "正在匹配…" : subjectCandidates.length ? "重新匹配" : "匹配 QS 学科"}</button>
                  {subjectCandidates.length > 0 && <div className={styles.subjectCandidates}>{subjectCandidates.map((subject) => <button type="button" key={subject} className={selectedSubject === subject ? styles.selectedSubject : ""} onClick={() => { setSelectedSubject(subject); setSubjectMappingError(""); }}>{selectedSubject === subject ? "✓ " : ""}{subject}</button>)}</div>}
                  {subjectMappingError && <p className={styles.subjectError}>{subjectMappingError}</p>}
                </div>}
                <div className={styles.filterRow}><label><span>QS 排名从</span><input type="number" min="1" value={rankingMin} onChange={(event) => setRankingMin(event.target.value)} placeholder="1" /></label><label><span>QS 排名到</span><input type="number" min="1" value={rankingMax} onChange={(event) => setRankingMax(event.target.value)} placeholder="100" /></label></div>
                <label><span>其他偏好 <small>可选</small></span><textarea rows={4} value={additionalPreferences} onChange={(event) => setAdditionalPreferences(event.target.value)} placeholder="例如：偏好大城市、希望有实习机会、预算范围……" /></label>
                <p className={styles.liveFilterHint}>{isDiscovering ? "正在更新院校列表…" : "院校列表会随筛选条件实时更新"}</p>
              </section>

              <section className={styles.universityResults} aria-live="polite">
                {target?.mode === "explore" && <div className={styles.resultSummary}><div><span>覆盖国家 / 地区</span><strong>{target.countries.length || "全球"}</strong></div><i /><div><span>候选院校</span><strong>{candidateUniversities.length}</strong></div><i /><div><span>排名版本</span><strong>{candidateUniversities[0] ? `QS ${candidateUniversities[0].ranking_edition}` : "—"}</strong></div></div>}
                <div className={styles.resultsTitle}><div><p className={styles.eyebrow}>DISCOVER UNIVERSITIES</p><h2>发现院校</h2></div>{target?.mode === "explore" && <span>{target.ranking.basis === "subject" ? `QS ${target.ranking_subject} 学科排名 ${candidateUniversities[0]?.ranking_edition ?? 2026}` : `QS 世界大学综合排名 ${candidateUniversities[0]?.ranking_edition ?? 2027}`} · {target.ranking.min}–{target.ranking.max}</span>}</div>
                {isDiscovering && <div className={styles.discoveryNotice}>正在查询本地 QS 官方排名数据…</div>}
                {!isDiscovering && discoveryError && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}><p>{discoveryError}</p>{target?.mode === "explore" && target.ranking.type === "QS" && <button type="button" onClick={() => void discoverUniversities(target)}>重新检索</button>}</div>}
                {!isDiscovering && target?.mode === "explore" && !discoveryError && candidateUniversities.length === 0 && <div className={styles.discoveryNotice}>暂未找到可靠的院校排名结果，请调整筛选条件后重新应用。</div>}
                {!target && <div className={styles.discoveryNotice}>正在加载 QS 2027 综合排名院校…</div>}
                <div className={styles.universityGrid}>{target?.mode === "explore" && candidateUniversities.map((candidateUniversity) => {
                  const key = candidateUniversity.university;
                  const programs = programsByUniversity[key];
                  const isLoading = loadingUniversity === key;
                  return <article className={styles.universityCard} key={key}>
                    <div className={styles.universityTop}><div className={styles.universityMonogram}>{candidateUniversity.university.slice(0, 1)}</div><div className={styles.universityName}><h3>{candidateUniversity.university}</h3><p><span>{candidateUniversity.country}</span> · {candidateUniversity.ranking_basis === "subject" ? candidateUniversity.ranking_subject : "世界大学综合排名"}</p></div>{candidateUniversity.ranking_basis === "subject" && candidateUniversity.subject_ranking ? <div className={`${styles.rankingBadge} ${styles.dualRankingBadge}`}><div><small>QS 综合 {candidateUniversity.overall_ranking?.edition ?? 2027}</small><strong><OverallRankingValue university={candidateUniversity} /></strong></div><div><small>QS {candidateUniversity.subject_ranking.subject} · {candidateUniversity.subject_ranking.edition}</small><strong>#{candidateUniversity.subject_ranking.rank_display}</strong></div></div> : <div className={styles.rankingBadge}><small>QS 综合 {candidateUniversity.overall_ranking?.edition ?? candidateUniversity.ranking_edition}</small><strong>#{candidateUniversity.overall_ranking?.rank_display ?? candidateUniversity.rank_display}</strong></div>}</div>
                    <div className={styles.universityFoot}><span>本地 QS 数据 · {candidateUniversity.school_official_url ? <a href={candidateUniversity.school_official_url} target="_blank" rel="noopener noreferrer">学校官网 ↗</a> : "官网暂未确认"}</span><button type="button" disabled={Boolean(loadingUniversity) || !target.target_major.trim()} onClick={() => void discoverPrograms(target, candidateUniversity)}>{!target.target_major.trim() ? "填写目标专业后查看项目" : isLoading ? "正在检索项目…" : programs ? "收起相关项目 ↑" : "查看相关项目 →"}</button></div>
                    {programErrors[key] && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}>{programErrors[key]}</div>}
                    {programs && <div className={styles.expandedPrograms}>
                      {programs.length === 0 ? <p className={styles.noPrograms}>AI Web Search 暂未找到与目标专业高度相关的硕士项目。</p> : programs.map((candidate) => {
                        const confirming = isConfirmingTarget && confirmationUniversity === key;
                        return <div className={styles.programRow} key={candidate.official_program_url}><div><span>{candidate.degree_type || "硕士项目"}</span><h4>{candidate.program}</h4>{candidate.relevance_reason && <p>{candidate.relevance_reason}</p>}<a href={candidate.official_program_url} target="_blank" rel="noopener noreferrer">查看项目官网 ↗</a></div><button type="button" disabled={isConfirmingTarget} onClick={() => void confirmTargetProgram({ university: candidate.university, program: candidate.program, official_program_url: candidate.official_program_url })}>{confirming ? "正在处理…" : "设为目标项目"}</button></div>;
                      })}
                      {confirmationError && confirmationUniversity === key && <div className={styles.confirmationError}>{confirmationError}</div>}
                      <div className={styles.manualProgramEntry}>
                        {manualUniversity === key ? <form onSubmit={(event) => { event.preventDefault(); void verifyManualProgramUrl(key); }}>
                          <div className={styles.manualEntryHeading}><strong>手动添加项目</strong><button type="button" onClick={() => { setManualUniversity(null); setManualProgramUrl(""); setManualVerifiedProgram(null); setConfirmationError(""); }}>取消</button></div>
                          <label><span>学校</span><input value={key} readOnly /></label>
                          <label><span>官方项目链接 *</span><input type="url" value={manualProgramUrl} onChange={(event) => { setManualProgramUrl(event.target.value); setManualVerifiedProgram(null); setConfirmationError(""); }} placeholder="https://www.ox.ac.uk/…" required /></label>
                          <p className={styles.manualEntryHint}>请粘贴具体项目页面链接，AI Web Search 会识别项目名称与页面。</p>
                          <button className={styles.primaryAction} type="submit" disabled={isConfirmingTarget || !manualProgramUrl.trim()}>{isConfirmingTarget && confirmationUniversity === key ? "正在识别…" : "识别项目链接"}</button>
                          {manualVerifiedProgram?.university === key && <div className={`${styles.programRow} ${styles.manualVerifiedCard}`}>
                            <div><span>{manualVerifiedProgram.university}</span><h4>{manualVerifiedProgram.program}</h4><p className={styles.verifiedStatus}>✓ AI Web Search 已识别</p><a href={manualVerifiedProgram.official_program_url} target="_blank" rel="noopener noreferrer">查看项目页面 ↗</a></div>
                            <button type="button" onClick={() => beginEntryCycleSelection(manualVerifiedProgram)}>设为目标项目</button>
                          </div>}
                        </form> : <div className={styles.manualEntryPrompt}><span>没找到你想申请的项目？</span><button type="button" onClick={() => { setManualUniversity(key); setManualProgramUrl(""); setManualVerifiedProgram(null); setConfirmationError(""); }}>手动添加项目</button></div>}
                      </div>
                    </div>}
                  </article>;
                })}</div>
              </section>
            </div>
          </>}

          {targetStep === "entry_cycle" && pendingTargetProgram && <div className={styles.requirementsReview}>
            <button type="button" className={styles.backButton} onClick={() => setTargetStep("explore")}>← 返回院校筛选</button>
            <div className={styles.requirementsHeading}><div><p className={styles.eyebrow}>APPLICATION CYCLE</p><h1>选择目标申请周期</h1><p>确认目标项目后，再选择入学年份和学期；该信息将用于检索对应周期的官方 Timeline。</p></div></div>
            <div className={styles.activeTargetCard}><span>已选择目标项目</span><strong>{pendingTargetProgram.university}</strong><h2>{pendingTargetProgram.program}</h2></div>
            <section className={styles.targetForm}>
              <div className={styles.filterRow}><label><span>目标入学年份</span><input type="number" min={DEFAULT_ENTRY_YEAR - 1} max="2100" value={intendedEntryYear} onChange={(event) => setIntendedEntryYear(event.target.value)} /></label><label><span>目标入学学期</span><select value={intendedEntryTerm} onChange={(event) => setIntendedEntryTerm(event.target.value as typeof intendedEntryTerm)}><option value="fall">Fall / 秋季</option><option value="spring">Spring / 春季</option><option value="summer">Summer / 夏季</option><option value="winter">Winter / 冬季</option></select></label></div>
              <div className={styles.requirementsActions}><p>若该申请周期的官网时间尚未公布，Timeline 将保持未找到状态，后续计划只按准备阶段生成。</p><button type="button" className={styles.primaryAction} onClick={confirmEntryCycle} disabled={!Number(intendedEntryYear)}>确认申请周期 <span>→</span></button></div>
            </section>
          </div>}

          {targetStep === "requirements" && activeTargetProgram && <div className={styles.requirementsReview}>
            <div className={styles.requirementsHeading}><div><p className={styles.eyebrow}>REQUIREMENTS REVIEW</p><h1>目标项目申请要求</h1><p>AI 根据公开网页整理，仅供参考；最终申请要求以院校最新官方信息为准。</p></div><div className={styles.requirementsHeadingActions}><button type="button" onClick={() => setTargetStep("explore")}>← 返回院校筛选</button><a href={activeTargetProgram.official_program_url} target="_blank" rel="noopener noreferrer">查看项目官网 ↗</a></div></div>
            <div className={styles.activeTargetCard}><span>已选择目标项目</span><strong>{activeTargetProgram.university}</strong><h2>{activeTargetProgram.program}</h2></div>
            {isLoadingTimeline && <div className={styles.timelineCard}><div className={styles.timelineHeading}><div><span>APPLICATION TIMELINE</span><h2>正在检索官方申请时间…</h2></div></div></div>}
            {!isLoadingTimeline && timelineError && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}><p>{timelineError}</p><button type="button" onClick={() => void retrieveTimeline(activeTargetProgram)}>重新获取时间线</button></div>}
            {!isLoadingTimeline && applicationTimeline && <article className={styles.timelineCard}>
              <div className={styles.timelineHeading}><div><span>APPLICATION TIMELINE</span><h2>申请时间线</h2></div><strong className={applicationTimeline.status === "complete" ? styles.timelineComplete : applicationTimeline.status === "partial" ? styles.timelinePartial : styles.timelineMissing}>{applicationTimeline.status === "complete" ? "信息完整" : applicationTimeline.status === "partial" ? "部分信息" : "该申请周期官方时间尚未公布"}</strong></div>
              <div className={styles.timelineMeta}><div><span>Admission Cycle</span><strong>{applicationTimeline.admission_cycle}</strong></div><div><span>Open Date</span><strong>{applicationTimeline.application_open_date ?? "暂未找到"}</strong>{applicationTimeline.application_open_source_url && <a href={applicationTimeline.application_open_source_url} target="_blank" rel="noopener noreferrer">查看官网来源 ↗</a>}</div><div><span>Rolling Admission</span><strong>{applicationTimeline.rolling_admission === true ? "是" : applicationTimeline.rolling_admission === false ? "否" : "官网未明确"}</strong>{applicationTimeline.rolling_admission_source_url && <a href={applicationTimeline.rolling_admission_source_url} target="_blank" rel="noopener noreferrer">查看官网来源 ↗</a>}</div></div>
              {applicationTimeline.application_deadlines.length > 0 ? <div className={styles.timelineDeadlines}><h3>Application Deadlines</h3>{applicationTimeline.application_deadlines.map((deadline, index) => <div key={`${deadline.label}-${deadline.date}-${index}`}><div><span>{deadline.type}</span><strong>{deadline.label}</strong></div><time>{deadline.date}</time><a href={deadline.source_url} target="_blank" rel="noopener noreferrer">查看官网来源 ↗</a></div>)}</div> : <p className={styles.timelineEmpty}>{applicationTimeline.status === "not_found" ? "该申请周期官方时间尚未公布" : "当前官方信息中暂未找到该入学周期的申请截止日期。"}</p>}
            </article>}
            {isLoadingRequirements && <div className={styles.requirementsLoading}><i /><strong>AI 正在搜索并整理申请要求…</strong><span>将按 7 类返回 Requirements Snapshot，请稍候。</span></div>}
            {!isLoadingRequirements && requirementsError && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}><p>{requirementsError}</p><button type="button" onClick={() => void retrieveRequirements(activeTargetProgram)}>重新分析</button></div>}
            {!isLoadingRequirements && requirementsReview && <>
              <div className={styles.requirementsGrid}>{REQUIREMENT_CATEGORIES.map(({ id, label }) => {
                const category = requirementsReview.categories.find((item) => item.category === id) ?? { category: id, coverage: "not_found" as const, requirements: [] };
                const statusClass = category.coverage === "official_verified"
                  ? styles.coverageOfficial
                  : category.coverage === "model_memory_unverified"
                    ? styles.coverageMemory
                    : category.coverage === "user_supplied"
                      ? styles.coverageUser
                      : styles.coverageMissing;
                return <article className={styles.requirementCard} key={id}>
                  <div className={styles.requirementCardHeading}><h2>{label}</h2><span className={statusClass}>{COVERAGE_LABELS[category.coverage]}</span></div>
                  {category.coverage === "model_memory_unverified" && <p className={styles.memoryRequirementNote}>以下内容是 AI 参考，当前未确认官方来源；它会参与匹配分析，请结合院校最新信息继续核对。</p>}
                  {category.requirements.length > 0 ? <div className={styles.requirementItems}>{category.requirements.map((requirement, index) => <div key={`${requirement.requirement}-${index}`}><p>{requirement.requirement}</p>{requirement.requirement_zh && <p className={styles.requirementTranslation}>{requirement.requirement_zh}</p>}<div><span>{IMPORTANCE_LABELS[requirement.importance]}</span><span>{SOURCE_LEVEL_LABELS[requirement.source_level]}</span><span>{requirement.source_type === "user_supplied" ? "用户提供" : requirement.verification_status === "model_memory_unverified" ? "AI 参考 · 当前未确认官方来源" : "AI 检索自官网"}</span><span>{TEMPORAL_APPLICABILITY_LABELS[requirement.temporal_applicability]}{requirement.source_cycle ? ` · ${requirement.source_cycle}` : ""}</span></div>{requirement.temporal_note && <p className={styles.requirementTranslation}>周期说明：{requirement.temporal_note}</p>}{requirement.source_url && <a href={requirement.source_url} target="_blank" rel="noopener noreferrer">{requirement.verification_status === "model_memory_unverified" ? "查看参考页面 ↗" : "查看官网来源 ↗"}</a>}</div>)}</div> : <p className={styles.missingRequirement}>DeepSeek 本次既未获得可用官网信息，也无法提供合理 AI 参考；后续 Gap Analysis 将按“信息不足”处理。</p>}
                  {(category.coverage === "not_found" || category.coverage === "model_memory_unverified") && supplementCategory !== id && <button type="button" className={styles.supplementButton} onClick={() => { setSupplementCategory(id); setSupplementRequirement(""); setSupplementSourceUrl(""); }}>补充信息</button>}
                  {supplementCategory === id && <form className={styles.supplementForm} onSubmit={saveRequirementSupplement}><label><span>官网要求原文 *</span><textarea rows={4} value={supplementRequirement} onChange={(event) => setSupplementRequirement(event.target.value)} required /></label><label><span>来源页面 URL <small>推荐</small></span><input type="url" value={supplementSourceUrl} onChange={(event) => setSupplementSourceUrl(event.target.value)} placeholder="https://…" /></label><div><button type="button" onClick={() => setSupplementCategory(null)}>取消</button><button type="submit" disabled={!supplementRequirement.trim()}>保存</button></div></form>}
                </article>;
              })}</div>
              <div className={styles.requirementsActions}><p>官网来源、AI 参考和用户补充都可参与匹配；AI 参考会始终保留来源状态，暂未找到项按信息不足处理。</p><button type="button" className={styles.primaryAction} onClick={() => void startGapInterview()} disabled={isPlanningGap}>{isPlanningGap ? "正在规划匹配访谈…" : "开始匹配分析"} <span>→</span></button></div>
              {gapError && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}>{gapError}</div>}
            </>}
          </div>}

          {targetStep === "gap_interview" && activeTargetProgram && gapPlan && <div className={styles.gapInterviewStage}>
            <div className={styles.gapInterviewHeading}><p className={styles.eyebrow}>ADAPTIVE GAP INTERVIEW</p><h1>补充匹配信息</h1><p>我会根据当前项目的实际申请要求，只询问完成匹配分析所需要的信息，不会重复询问已经提供过的内容。</p><div><strong>{activeTargetProgram.university}</strong><span>{activeTargetProgram.program}</span></div></div>
            <div className={styles.gapInterviewMeta}><span>还需补充 <strong>{Math.max(gapPlan.questions.length - gapQuestionIndex, 0)}</strong> 项信息</span><span>已复用 {gapPlan.reusable_evidence.length} 项已有证据</span></div>
            <div className={styles.gapChat}>
              <div className={styles.messages} aria-live="polite">
                {gapTurns.map((turn, index) => <div key={`${turn.question}-${index}`}><div className={styles.assistantRow}><div className={styles.miniAvatar}>知</div><p>{turn.question}</p></div><div className={styles.userRow}><p>{turn.answer}</p></div></div>)}
                {!isAnalyzingGap && gapPlan.questions[gapQuestionIndex] && <div className={styles.assistantRow}><div className={styles.miniAvatar}>知</div><p>{gapFollowUpQuestion || gapPlan.questions[gapQuestionIndex].question}</p></div>}
                {isAnalyzingGap && <div className={`${styles.assistantRow} ${styles.thinkingRow}`}><div className={styles.miniAvatar}>知</div><p><span>●</span><span>●</span><span>●</span> 正在生成 Gap Table</p></div>}
                {gapError && <div className={styles.inlineError}>{gapError}</div>}
              </div>
              <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void submitGapAnswer(gapInput); }}>
                <label htmlFor="gap-answer">你的回答</label>
                <div className={styles.inputShell}><textarea id="gap-answer" rows={2} value={gapInput} disabled={isParsingGapAnswer || isAnalyzingGap} onChange={(event) => setGapInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitGapAnswer(gapInput); } }} placeholder="可以直接回答，也可以说不知道、不记得或暂时没有" /><button type="submit" disabled={!gapInput.trim() || isParsingGapAnswer || isAnalyzingGap} aria-label="发送回答">↑</button></div>
                <div className={styles.gapQuickAnswers}><button type="button" onClick={() => void submitGapAnswer("不知道，暂时无法提供")}>不知道</button><button type="button" onClick={() => void submitGapAnswer("暂时没有")}>暂时没有</button></div>
              </form>
            </div>
          </div>}

          {targetStep === "gap_results" && activeTargetProgram && gapAnalysis && <div className={styles.gapResultsStage}>
            <div className={styles.gapResultsHeading}><div><p className={styles.eyebrow}>GAP TABLE</p><h1>申请匹配结果</h1><p>{activeTargetProgram.university} · {activeTargetProgram.program}</p></div><button type="button" className={styles.backButton} onClick={() => setTargetStep("requirements")}>返回查看申请要求</button></div>
            <div className={styles.gapSummary}>{(["met", "partial", "not_met", "unknown"] as GapStatus[]).map((status) => <div key={status}><span>{status === "met" ? "满足" : status === "partial" ? "部分满足" : status === "not_met" ? "未满足" : "信息不足"}</span><strong>{gapAnalysis.results.filter((item) => item.status === status).length}</strong></div>)}</div>
            <div className={styles.gapTableWrap}><table className={styles.gapTable}><thead><tr><th>目标要求</th><th>类型</th><th>匹配状态</th><th>用户证据</th><th>差距</th><th>来源</th></tr></thead><tbody>{gapAnalysis.results.map((result) => <tr key={result.requirement_id}><td><strong>{result.requirement}</strong>{result.requirement_zh && <span className={styles.gapRequirementTranslation}>{result.requirement_zh}</span>}<small>{result.reason}</small></td><td>{REQUIREMENT_CATEGORIES.find((item) => item.id === result.category)?.label ?? result.category}</td><td><span className={result.status === "met" ? styles.gapStatusMet : result.status === "partial" ? styles.gapStatusPartial : result.status === "not_met" ? styles.gapStatusNotMet : styles.gapStatusUnknown}>{result.status === "met" ? "满足" : result.status === "partial" ? "部分满足" : result.status === "not_met" ? "未满足" : "信息不足"}</span></td><td>{result.user_evidence}</td><td>{result.gap}</td><td><div>{result.requirement_verification_status === "user_supplied" ? "用户补充要求" : result.requirement_verification_status === "model_memory_unverified" ? "AI 参考 · 当前未确认官方来源" : result.source_url ? <a href={result.source_url} target="_blank" rel="noopener noreferrer">官网来源 ↗</a> : "AI 检索自官网"}</div><small>{TEMPORAL_APPLICABILITY_LABELS[result.temporal_applicability]}{result.source_cycle ? ` · ${result.source_cycle}` : ""}{result.temporal_note ? `：${result.temporal_note}` : ""}</small></td></tr>)}</tbody></table></div>
            {gapAnalysis.informational_requirements.length > 0 && <div className={styles.informationalRequirements}><strong>以下为信息型要求，不参与匹配判断</strong>{gapAnalysis.informational_requirements.map((item) => <p key={item.requirement_id}>{item.requirement}</p>)}</div>}
            <div className={styles.planningLaunch}><div><strong>生成统一申请时间轴</strong><p>将 Gap Table、官方 Timeline 和当前日期合并为申请级行动计划。</p></div><button type="button" className={styles.primaryAction} onClick={() => void generateActionPlan()} disabled={isPlanningActions}>{isPlanningActions ? "正在生成行动计划…" : "生成 Action Plan"} <span>→</span></button></div>
            {actionPlanError && <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}>{actionPlanError}</div>}
          </div>}

          {targetStep === "planning" && activeTargetProgram && actionPlan && <div className={styles.actionPlanStage}>
            <div className={styles.actionPlanHeading}><div><p className={styles.eyebrow}>PLANNING WORKFLOW</p><h1>申请行动计划</h1><p>{activeTargetProgram.university} · {activeTargetProgram.program}</p></div><button type="button" className={styles.backButton} onClick={() => setTargetStep("gap_results")}>返回 Gap Table</button></div>
            {actionPlan.timeline_status === "not_found" && <div className={styles.actionPlanNotice}>当前未获取到该项目明确的官方申请时间，以下计划仅按任务优先级和准备阶段生成，不包含精确提交日期。</div>}
            <div className={styles.actionPlanMeta}>
              <div><span>当前日期</span><strong>{actionPlan.current_date}</strong></div>
              <div><span>Ready by</span><strong>{actionPlan.ready_by_date ?? "准备至可提交状态 / Ready for submission"}</strong></div>
              <div><span>Application Deadline</span><strong>{actionPlan.application_deadline ?? "官网暂未明确"}</strong>{!actionPlan.deadline_is_precise && <small>不会据此生成虚假精确日期</small>}</div>
            </div>
            {actionPlan.actions.length === 0 ? <div className={styles.actionPlanEmpty}>当前所有可匹配要求均已满足，无需生成额外任务。</div> : <div className={styles.unifiedTimeline}>
              {groupPlanningActions(actionPlan.actions).map((group) => <section key={group.timePeriod} className={styles.actionPeriod}>
                <div className={styles.actionPeriodLabel}><span /> <strong>{planningDisplayText(group.timePeriod, actionPlan.deadline_is_precise)}</strong></div>
                <div className={styles.actionPeriodItems}>{group.items.map((action) => <article key={action.action_id} className={action.plan_track === "optional" ? styles.optionalAction : styles.mainAction}>
                  <div className={styles.actionCardTop}><span>{action.plan_track === "optional" ? "可选提升项" : action.action_kind === "confirm_information" ? "信息确认" : "主计划"}</span>{action.target_date && <time>{action.target_date}</time>}</div>
                  <h2>{planningDisplayText(action.action, actionPlan.deadline_is_precise)}</h2>
                  <p>{planningDisplayText(action.reason, actionPlan.deadline_is_precise)}</p>
                  <div className={styles.actionTags}><span>{action.priority === "high" ? "高优先级" : action.priority === "optional" ? "不阻塞主计划" : "常规优先级"}</span><span>{action.status === "pending" ? "待开始" : action.status}</span>{action.parallel_group && <span>可并行 · {action.parallel_group}</span>}</div>
                </article>)}</div>
              </section>)}
            </div>}
          </div>}
        </section>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}><div className={styles.brand}><span className={styles.brandMark}>知</span><span>知途留学</span></div><span className={styles.status}>基础信息 · 约 1 分钟</span></header>
      <div className={styles.workspace}>
        <aside className={styles.sidebar} aria-label="访谈进度">
          <div><p className={styles.eyebrow}>MINIMAL PROFILE</p><h1>先认识一下你的本科背景</h1><p className={styles.sidebarIntro}>这里只收集本科院校和专业。成绩、课程与经历会在选定项目后，根据当前 Requirements 按需询问。</p></div>
          <div className={styles.progressBlock}><div className={styles.progressMeta}><span>完成进度</span><strong>{progress}%</strong></div><div className={styles.progressTrack}><span style={{ width: `${progress}%` }} /></div></div>
          <ol className={styles.steps}>{topics.map((topic, index) => {
            const state = index < topicIndex ? "done" : index === topicIndex ? "active" : "";
            return <li key={topic.id} className={styles[state]}><span>{index < topicIndex ? "✓" : index + 1}</span><div><strong>{topic.label}</strong><small>{index < topicIndex ? "已完成" : index === topicIndex ? "进行中" : "待填写"}</small></div></li>;
          })}</ol>
          <p className={styles.privacy}>Ask once · 后续匹配会复用</p>
        </aside>
        <section className={styles.chat} aria-label="背景访谈对话">
          <div className={styles.chatHeader}><div className={styles.advisorAvatar}>顾</div><div><strong>申请顾问小知</strong><span><i /> AI 正在协助整理</span></div><span className={styles.stepCount}>{topicIndex + 1} / {topics.length}</span></div>
          <div className={styles.messages} aria-live="polite">
            <div className={styles.dayLabel}>今天</div>
            <div className={styles.welcome}><span>👋</span><div><strong>你好，很高兴认识你！</strong><p>先告诉我本科院校和专业即可。其他背景会等目标项目要求明确后再按需补充。</p><button type="button" className={styles.skipProfileAction} onClick={skipProfile}>暂时跳过，直接查看院校和项目 →</button></div></div>
            {messages.map((message, index) => message.role === "assistant" ? <div className={styles.assistantRow} key={index}><div className={styles.miniAvatar}>知</div><p>{message.content}</p></div> : <div className={styles.userRow} key={index}><p>{message.content}</p></div>)}
            {isProcessing ? <div className={`${styles.assistantRow} ${styles.thinkingRow}`}><div className={styles.miniAvatar}>知</div><p><span>●</span><span>●</span><span>●</span> 正在记录基础信息</p></div> : <div className={styles.assistantRow}><div className={styles.miniAvatar}>知</div><p>{currentQuestion}</p></div>}
            {errorMessage && <div className={styles.inlineError}>{errorMessage}</div>}
          </div>
          <form className={styles.composer} onSubmit={handleSubmit}>
            <label htmlFor="answer">你的回答</label>
            <div className={styles.inputShell}><textarea ref={textareaRef} id="answer" rows={2} value={input} disabled={isProcessing} onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown} placeholder={currentTopic.hint} autoFocus /><button type="submit" disabled={!input.trim() || isProcessing} aria-label="发送回答">↑</button></div>
            <div className={styles.composerFooter}><span>按 Enter 发送 · Shift + Enter 换行</span></div>
          </form>
        </section>
      </div>
    </main>
  );
}
