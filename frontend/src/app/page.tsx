"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import styles from "./page.module.css";
import StandardProfileInterview from "@/features/standard-profile/StandardProfileInterview";
import { EMPTY_STANDARD_PROFILE, StandardUserProfile } from "@/features/standard-profile/profile";
import { CachedProfileStatus, profileEntryView as profileEntryViewForStatus, readStandardProfileCache, writeStandardProfileCache } from "@/features/standard-profile/profile-cache";
import SpecialRequirementInterview, { SpecialInterviewPlan, SpecialInterviewSubmission } from "@/features/special-interview/SpecialRequirementInterview";
import { mergeReusableEvidence, readReusableEvidence, writeReusableEvidence } from "@/features/special-interview/evidence-cache";
import { nextStepAfterSpecialExtraction } from "@/features/special-interview/workflow";

type ProfileStatus = "not_started" | "completed" | "skipped";
type UserProfile = StandardUserProfile;
type ExploreTarget = {
  mode: "explore";
  countries: string[];
  target_major: string;
  ranking: { type: "QS"; basis: "overall" | "subject"; min: number | null; max: number | null };
  ranking_subject_id: string | null;
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
type RequirementApplicabilityStage = "pre_admission" | "conditional_admission" | "in_program" | "informational" | "unclear";
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
  applicability_stage: RequirementApplicabilityStage;
};
type RequirementCategoryReview = { category: RequirementCategory; coverage: RequirementCoverage; requirements: RequirementItem[] };
type TargetProgramRequirementsReview = { target_program: TargetProgram; checked_at: string; cache_source: "live" | "runtime_cache" | "seed"; categories: RequirementCategoryReview[] };
type EvidenceAvailability = "known" | "known_negative" | "unknown";
type GapStatus = "met" | "partial" | "not_met" | "unknown";
type GapReasonCode = "matched" | "partially_matched" | "requirement_not_met" | "user_evidence_missing" | "temporal_unconfirmed" | "previous_cycle_reference" | "semantic_evidence_insufficient" | "conditional_pending";
type ConditionalApplicabilityState = "not_conditional" | "active" | "inactive" | "pending";
type GapEvidenceType = "education_university" | "education_major" | "academic_score" | "language_score" | "standardized_score" | "courses" | "material_status" | "material_quantity" | "experience" | "prerequisite_course" | "user_course" | "generic";
type UserEvidence = { evidence_type: GapEvidenceType; key: string; value: unknown; raw_answer: string; availability: EvidenceAvailability; updated_at: string; source_requirement_ids: string[] };
type GapEvidenceNeed = { key: string; evidence_type: GapEvidenceType; label: string; already_known: boolean; required_fields: string[]; evidence_group: string | null; group_relation: "all" | "any"; minimum: number | null; component_minimum: number | null; required_quantity: number | null };
type GapQuestionControlType = "boolean" | "boolean_group" | "experience_form" | "single_select" | "multi_select" | "number" | "number_group" | "date" | "short_text" | "text_fallback";
type GapQuestionOption = { value: string; label: string; evidence_key: string | null; evidence_value: unknown };
type GapQuestionField = { field_id: string; label: string; evidence_key: string; value_path: string; required: boolean; placeholder: string | null };
type GapQuestion = {
  question_id: string;
  requirement_id: string | null;
  question: string;
  prompt: string;
  evidence_keys: string[];
  expected_evidence_keys: string[];
  allowed_evidence_keys: string[];
  evidence_group: string | null;
  group_relation: "all" | "any";
  control_type: GapQuestionControlType;
  options: GapQuestionOption[];
  fields: GapQuestionField[];
  validation: { required: boolean; minimum: number | null; maximum: number | null; step: number | null; min_selections: number | null; max_selections: number | null };
  allow_unknown: boolean;
  allow_negative: boolean;
  allow_other: boolean;
  schema_status: "valid" | "invalid" | "fallback" | "generation_error";
  schema_error_code: string | null;
  repair_attempts: number;
};
type GapEvidenceResponse = { evidence: UserEvidence[]; missing_slots: string[]; follow_up_question: string | null; satisfied_evidence_groups: string[]; parser_calls: number };
type SelectedLanguageTest = { questionId: string; evidenceKey: "ielts" | "toefl"; label: string };
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
  conditional_state: ConditionalApplicabilityState;
  conditional: {
    is_conditional: boolean;
    condition_text: string | null;
    controlling_evidence_keys: string[];
    predicate_relation: "all" | "any";
    predicates: { evidence_key: string; operator: "equals" | "in"; expected_values: string[] }[];
  };
  matchable: boolean;
  informational_reason: string;
  match_strategy: "deterministic" | "semantic" | "hybrid";
  evidence_needs: GapEvidenceNeed[];
  constraint: { kind: string; options: unknown[] };
};
type GapPlan = { target_program: TargetProgram; requirements: GapPlannedRequirement[]; questions: GapQuestion[]; reusable_evidence: UserEvidence[]; planning_llm_requests: number };
type GapResult = { requirement_id: string; category: RequirementCategory; requirement: string; requirement_zh?: string | null; requirement_verification_status: "official_verified" | "model_memory_unverified" | "user_supplied"; importance: RequirementItem["importance"]; status: GapStatus; reason_code: GapReasonCode; user_evidence: string; gap: string; reason: string; source_url: string | null; source_cycle: string | null; temporal_applicability: RequirementTemporalApplicability; temporal_note: string | null; conditional_state: ConditionalApplicabilityState };
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
  priority_order: number;
  timing_status: "scheduled" | "urgent" | "priority_only";
};
type PlanningConfirmationItem = { source_gap_id: string; title: string; reason: string; action_kind: "confirm_information"; target_date: null };
type PlanningEligibilityRisk = { source_gap_id: string; title: string; reason: string; target_date: null };
type ActionPlan = {
  target_program: TargetProgram;
  generated_at: string;
  current_date: string;
  timeline_status: ApplicationTimeline["status"];
  application_deadline: string | null;
  application_deadline_label: string | null;
  deadline_is_precise: boolean;
  ready_by_date: string | null;
  needs_confirmation: PlanningConfirmationItem[];
  eligibility_risks: PlanningEligibilityRisk[];
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
type QSSubjectOption = { subject_id: string; subject_name: string; edition: number };
type QSSubjectListResponse = { edition: number; subjects: QSSubjectOption[] };

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
const UNKNOWN_GAP_REASON_LABELS: Partial<Record<GapReasonCode, string>> = {
  user_evidence_missing: "信息不足",
  temporal_unconfirmed: "目标周期待确认",
  previous_cycle_reference: "上一周期参考",
  semantic_evidence_insufficient: "仍需语义确认",
  conditional_pending: "适用条件待确认",
};

function gapStatusLabel(result: GapResult): string {
  if (result.status === "met") return "满足";
  if (result.status === "partial") return "部分满足";
  if (result.status === "not_met") return "未满足";
  return UNKNOWN_GAP_REASON_LABELS[result.reason_code] ?? "信息不足";
}

const EMPTY_PROFILE: UserProfile = EMPTY_STANDARD_PROFILE;
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_ENTRY_YEAR = new Date().getUTCFullYear() + 1;
const TARGET_CONFIRMATION_TIMEOUT_MS = 35_000;
// Keep a 30s transport/UI margin beyond the backend Requirements deadline.
const REQUIREMENTS_RETRIEVAL_TIMEOUT_MS = 390_000;
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
  const [profile, setProfile] = useState<UserProfile>(EMPTY_PROFILE);
  const [profileHydrated, setProfileHydrated] = useState(false);
  const [profileEntryView, setProfileEntryView] = useState<"interview" | "summary" | "incomplete">("interview");
  const [showProfile, setShowProfile] = useState(false);
  const [profileStatus, setProfileStatus] = useState<ProfileStatus>("not_started");
  const [targetStep, setTargetStep] = useState<"explore" | "entry_cycle" | "requirements" | "special_interview" | "gap_interview" | "gap_results" | "planning" | null>(null);
  const [target, setTarget] = useState<ExploreTarget | null>(null);
  const [countries, setCountries] = useState<string[]>([]);
  const [targetMajor, setTargetMajor] = useState("");
  const [rankingBasis, setRankingBasis] = useState<"overall" | "subject">("overall");
  const [qsSubjects, setQsSubjects] = useState<QSSubjectOption[]>([]);
  const [subjectSearch, setSubjectSearch] = useState("");
  const [selectedSubjectId, setSelectedSubjectId] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("");
  const [subjectUncertain, setSubjectUncertain] = useState(false);
  const [isLoadingSubjects, setIsLoadingSubjects] = useState(false);
  const [subjectListError, setSubjectListError] = useState("");
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
  const [specialInterviewPlan, setSpecialInterviewPlan] = useState<SpecialInterviewPlan | null>(null);
  const [isSubmittingSpecialInterview, setIsSubmittingSpecialInterview] = useState(false);
  const [gapPlan, setGapPlan] = useState<GapPlan | null>(null);
  const [gapQuestionIndex, setGapQuestionIndex] = useState(0);
  const [gapFollowUpQuestion, setGapFollowUpQuestion] = useState("");
  const [gapFollowUpSlots, setGapFollowUpSlots] = useState<string[]>([]);
  const [gapFollowUpQuestionId, setGapFollowUpQuestionId] = useState("");
  const [satisfiedEvidenceGroups, setSatisfiedEvidenceGroups] = useState<string[]>([]);
  const [gapTurns, setGapTurns] = useState<{ question: string; answer: string }[]>([]);
  const [gapInput, setGapInput] = useState("");
  const [gapStructuredValues, setGapStructuredValues] = useState<Record<string, string | number | boolean>>({});
  const [gapSelectedOptions, setGapSelectedOptions] = useState<string[]>([]);
  const [selectedLanguageTest, setSelectedLanguageTest] = useState<SelectedLanguageTest | null>(null);
  const [gapOtherMode, setGapOtherMode] = useState(false);
  const [isPlanningGap, setIsPlanningGap] = useState(false);
  const [isParsingGapAnswer, setIsParsingGapAnswer] = useState(false);
  const [isRepairingGapQuestion, setIsRepairingGapQuestion] = useState(false);
  const [isAnalyzingGap, setIsAnalyzingGap] = useState(false);
  const [gapError, setGapError] = useState("");
  const [gapAnalysis, setGapAnalysis] = useState<GapAnalysisResponse | null>(null);
  const [actionPlan, setActionPlan] = useState<ActionPlan | null>(null);
  const [isPlanningActions, setIsPlanningActions] = useState(false);
  const [actionPlanError, setActionPlanError] = useState("");
  const discoveryRequestRef = useRef(0);

  useEffect(() => {
    const cached = readStandardProfileCache(window.localStorage);
    if (cached) {
      setProfile(cached.profile);
      setProfileStatus(cached.profileStatus);
      setProfileEntryView(profileEntryViewForStatus(cached.profileStatus));
    }
    setUserEvidence(readReusableEvidence<UserEvidence>(window.localStorage));
    setProfileHydrated(true);
  }, []);

  function persistProfile(nextProfile: UserProfile, status: CachedProfileStatus) {
    setProfile(nextProfile);
    setProfileStatus(status);
    writeStandardProfileCache(window.localStorage, nextProfile, status);
  }

  function updateProfileDraft(nextProfile: UserProfile) {
    persistProfile(nextProfile, "not_started");
  }

  function continueToExplore(status: CachedProfileStatus) {
    setProfileStatus(status);
    setShowProfile(true);
    setTargetStep("explore");
  }

  function returnToProfile() {
    setTargetStep(null);
    setShowProfile(false);
    setProfileEntryView(profileStatus === "completed" ? "summary" : "incomplete");
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
    setGapFollowUpQuestionId("");
    setSatisfiedEvidenceGroups([]);
    setGapStructuredValues({});
    setGapSelectedOptions([]);
    setSelectedLanguageTest(null);
    setGapOtherMode(false);
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

  async function retrieveRequirements(targetProgram: TargetProgram, forceRefresh = false) {
    if (isLoadingRequirements) return;
    setIsLoadingRequirements(true);
    setRequirementsError("");
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      REQUIREMENTS_RETRIEVAL_TIMEOUT_MS,
    );
    try {
      const response = await fetch(`${API_BASE_URL}/target-programs/requirements?force_refresh=${forceRefresh}`, {
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

  async function retrieveTimeline(targetProgram: TargetProgram, forceRefresh = false) {
    if (isLoadingTimeline) return;
    setIsLoadingTimeline(true);
    setTimelineError("");
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), TIMELINE_RETRIEVAL_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE_URL}/target-programs/timeline?force_refresh=${forceRefresh}`, {
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
      applicability_stage: "pre_admission",
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
    return mergeReusableEvidence(current, incoming);
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
      if (!response.ok) throw new Error("匹配分析生成失败，请重新尝试。");
      setGapAnalysis(data as GapAnalysisResponse);
      setTargetStep("gap_results");
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法完成匹配分析。");
    } finally {
      setIsAnalyzingGap(false);
    }
  }

  async function runExistingGapPlan(
    evidence: UserEvidence[],
    prerequisitePlan: SpecialInterviewPlan["authoritative_prerequisite_plan"] = specialInterviewPlan?.authoritative_prerequisite_plan ?? [],
  ) {
    if (!activeTargetProgram || !requirementsReview) return;
    const response = await fetch(`${API_BASE_URL}/gap/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_program: activeTargetProgram,
          requirements_review: requirementsReview,
          user_profile: profile,
          user_evidence: evidence,
          authoritative_prerequisite_plan: prerequisitePlan,
        }),
      });
    const data = await response.json();
    if (!response.ok) throw new Error("匹配分析生成失败，请重新尝试。");
    const plan = data as GapPlan;
    setGapPlan(plan);
    await analyzeGap(plan, evidence);
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
    setGapFollowUpQuestionId("");
    setSatisfiedEvidenceGroups([]);
    setSelectedLanguageTest(null);
    setSpecialInterviewPlan(null);
    try {
      const response = await fetch(`${API_BASE_URL}/special-interview/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_program: activeTargetProgram,
          requirements_review: requirementsReview,
          user_evidence: userEvidence,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error("项目特殊要求分析失败，请重新尝试。");
      const plan = data as SpecialInterviewPlan;
      setSpecialInterviewPlan(plan);
      if (nextStepAfterSpecialExtraction(plan.remaining_item_count) === "special_interview") {
        setTargetStep("special_interview");
      } else {
        await runExistingGapPlan(userEvidence, plan.authoritative_prerequisite_plan);
      }
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "匹配分析生成失败，请重新尝试。");
    } finally {
      setIsPlanningGap(false);
    }
  }

  async function submitSpecialInterview(answers: SpecialInterviewSubmission[]) {
    if (!activeTargetProgram || isSubmittingSpecialInterview) return;
    setIsSubmittingSpecialInterview(true);
    setGapError("");
    try {
      const response = await fetch(`${API_BASE_URL}/special-interview/evidence/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_program: activeTargetProgram, answers }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error("暂时无法保存这些背景信息，请重试。");
      const nextEvidence = mergeEvidence(userEvidence, data.evidence as UserEvidence[]);
      persistReusableEvidence(nextEvidence);
      await runExistingGapPlan(
        nextEvidence,
        specialInterviewPlan?.authoritative_prerequisite_plan ?? [],
      );
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法保存这些背景信息，请重试。");
    } finally {
      setIsSubmittingSpecialInterview(false);
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

  function currentGapEvidenceContext(question: GapQuestion) {
    if (!gapPlan) return { needs: [] as GapEvidenceNeed[], activeEvidenceKeys: [] as string[] };
    const allNeeds = gapPlan.requirements
      .flatMap((item) => item.evidence_needs);
    const allowedEvidenceKeys = (question.allowed_evidence_keys ?? []).length > 0
      ? question.allowed_evidence_keys
      : question.expected_evidence_keys;
    const needs = allowedEvidenceKeys.flatMap((key) => {
      const matching = allNeeds.filter((need) => need.key === key);
      const preferred = matching.find((need) => question.evidence_group && need.evidence_group === question.evidence_group) ?? matching[0];
      return preferred ? [preferred] : [];
    });
    const hasActiveFollowUp = gapFollowUpQuestionId === question.question_id && gapFollowUpSlots.length > 0;
    const activeEvidenceKeys = hasActiveFollowUp
      ? needs.filter((need) => gapFollowUpSlots.some((slot) => slot.startsWith(`${need.key}.`))).map((need) => need.key)
      : question.expected_evidence_keys;
    return { needs, activeEvidenceKeys: Array.from(new Set(activeEvidenceKeys)) };
  }

  async function finishGapEvidenceSubmission(
    question: GapQuestion,
    parsed: GapEvidenceResponse,
    displayedQuestion: string,
    answerLabel: string,
  ) {
    if (!gapPlan) return;
    const allNeeds = gapPlan.requirements
      .flatMap((item) => item.evidence_needs)
      .filter((need, index, all) => all.findIndex((item) => item.key === need.key) === index);
    const nextEvidence = mergeEvidence(userEvidence, parsed.evidence);
    const nextSatisfiedGroups = Array.from(new Set([...satisfiedEvidenceGroups, ...parsed.satisfied_evidence_groups]));
    persistReusableEvidence(nextEvidence);
    setSatisfiedEvidenceGroups(nextSatisfiedGroups);
    setGapTurns((current) => [...current, { question: displayedQuestion, answer: answerLabel }]);
    setGapInput("");
    setGapStructuredValues({});
    setGapSelectedOptions([]);
    setGapOtherMode(false);
    if (parsed.missing_slots.length > 0 && parsed.follow_up_question) {
      setGapFollowUpQuestion(parsed.follow_up_question);
      setGapFollowUpSlots(parsed.missing_slots);
      setGapFollowUpQuestionId(question.question_id);
      return;
    }
    setSelectedLanguageTest(null);
    setGapFollowUpQuestion("");
    setGapFollowUpSlots([]);
    setGapFollowUpQuestionId("");
    const currentRequirement = gapPlan.requirements.find(
      (item) => item.requirement_id === question.requirement_id,
    );
    const completedControllingQuestion = Boolean(
      currentRequirement?.conditional_state === "pending"
      && currentRequirement.conditional?.controlling_evidence_keys.some((key) =>
        question.expected_evidence_keys.includes(key),
      ),
    );
    if (completedControllingQuestion && activeTargetProgram && requirementsReview) {
      try {
        const response = await fetch(`${API_BASE_URL}/gap/plan`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_program: activeTargetProgram,
            requirements_review: requirementsReview,
            user_profile: profile,
            user_evidence: nextEvidence,
            authoritative_prerequisite_plan: specialInterviewPlan?.authoritative_prerequisite_plan ?? [],
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error("匹配分析生成失败，请重新尝试。");
        const refreshedPlan = data as GapPlan;
        setGapPlan(refreshedPlan);
        setGapQuestionIndex(0);
        if (refreshedPlan.questions.length === 0) {
          await analyzeGap(refreshedPlan, nextEvidence);
        }
        return;
      } catch (error) {
        setGapError(error instanceof Error ? error.message : "匹配分析生成失败，请重新尝试。");
        return;
      }
    }
    const evidenceByKey = new Map(nextEvidence.map((item) => [item.key.toLowerCase(), item]));
    const nextQuestionIndex = gapPlan.questions.findIndex((candidate, index) => index > gapQuestionIndex && candidate.expected_evidence_keys.some((key) => {
      const need = allNeeds.find((item) => item.key === key);
      return need && !evidenceByKey.has(key.toLowerCase()) && (!need.evidence_group || !nextSatisfiedGroups.includes(need.evidence_group));
    }));
    if (nextQuestionIndex < 0) {
      await analyzeGap(gapPlan, nextEvidence);
    } else {
      setGapQuestionIndex(nextQuestionIndex);
    }
  }

  async function submitStructuredGapAnswer(
    answer: { values?: Record<string, string | number | boolean>; selected_options?: string[]; terminal_state?: "known_negative" | "unknown" },
    answerLabel: string,
    questionOverride?: GapQuestion,
    displayedQuestionOverride?: string,
  ) {
    const question = questionOverride ?? gapPlan?.questions[gapQuestionIndex];
    if (!question || !gapPlan || isParsingGapAnswer) return;
    const { needs, activeEvidenceKeys } = currentGapEvidenceContext(question);
    setIsParsingGapAnswer(true);
    setGapError("");
    try {
      const displayedQuestion = displayedQuestionOverride ?? (gapFollowUpQuestionId === question.question_id && gapFollowUpQuestion
        ? gapFollowUpQuestion
        : question.prompt || question.question);
      const response = await fetch(`${API_BASE_URL}/gap/evidence/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: {
            ...question,
            evidence_keys: activeEvidenceKeys,
            expected_evidence_keys: activeEvidenceKeys,
          },
          evidence_needs: needs,
          existing_evidence: userEvidence,
          answer: {
            values: answer.values ?? {},
            selected_options: answer.selected_options ?? [],
            terminal_state: answer.terminal_state ?? null,
          },
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error("这个问题暂时无法正常提交，请尝试重新生成或使用补充说明。");
      }
      await finishGapEvidenceSubmission(question, data as GapEvidenceResponse, displayedQuestion, answerLabel);
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法记录这条回答。");
    } finally {
      setIsParsingGapAnswer(false);
    }
  }

  async function submitGapAnswer(value: string) {
    const answer = value.trim();
    const question = gapPlan?.questions[gapQuestionIndex];
    if (!answer || !question || !gapPlan || isParsingGapAnswer) return;
    const { needs, activeEvidenceKeys } = currentGapEvidenceContext(question);
    setIsParsingGapAnswer(true);
    setGapError("");
    try {
      const displayedQuestion = gapFollowUpQuestionId === question.question_id && gapFollowUpQuestion
        ? gapFollowUpQuestion
        : question.question;
      const response = await fetch(`${API_BASE_URL}/gap/evidence/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: {
            ...question,
            question: displayedQuestion,
            evidence_keys: activeEvidenceKeys,
            expected_evidence_keys: activeEvidenceKeys,
          },
          evidence_needs: needs,
          existing_evidence: userEvidence,
          answer,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "暂时无法记录这条回答。");
      await finishGapEvidenceSubmission(question, data as GapEvidenceResponse, displayedQuestion, answer);
    } catch (error) {
      setGapError(error instanceof Error ? error.message : "暂时无法记录这条回答。");
    } finally {
      setIsParsingGapAnswer(false);
    }
  }

  async function regenerateGapQuestion(question: GapQuestion) {
    if (!gapPlan || isRepairingGapQuestion || !question.requirement_id) return;
    const requirement = gapPlan.requirements.find((item) => item.requirement_id === question.requirement_id);
    if (!requirement) return;
    setIsRepairingGapQuestion(true);
    setGapError("");
    try {
      const response = await fetch(`${API_BASE_URL}/gap/questions/repair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          requirement,
          user_profile: profile,
          user_evidence: userEvidence,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error("这个问题暂时无法生成，请重新尝试。");
      const repaired = data as GapQuestion;
      setGapPlan((current) => current ? {
        ...current,
        questions: current.questions.map((item) => item.question_id === question.question_id ? repaired : item),
      } : current);
      setGapStructuredValues({});
      setGapSelectedOptions([]);
      setGapOtherMode(false);
      if (repaired.schema_status !== "valid" || repaired.control_type === "text_fallback") {
        setGapError("这个问题暂时无法生成，请重新尝试。");
      }
    } catch {
      setGapError("这个问题暂时无法生成，请重新尝试。");
    } finally {
      setIsRepairingGapQuestion(false);
    }
  }

  function beginLanguageScoreForm(question: GapQuestion, option: GapQuestionOption): boolean {
    const evidenceKey = option.evidence_key?.toLowerCase();
    if (evidenceKey !== "ielts" && evidenceKey !== "toefl") return false;
    const { needs } = currentGapEvidenceContext(question);
    const selectedNeed = needs.find((need) => need.key.toLowerCase() === evidenceKey);
    if (!selectedNeed || selectedNeed.evidence_type !== "language_score") return false;
    setGapTurns((current) => [...current, {
      question: question.prompt || question.question,
      answer: option.label,
    }]);
    setSelectedLanguageTest({
      questionId: question.question_id,
      evidenceKey,
      label: option.label,
    });
    setGapSelectedOptions([]);
    setGapStructuredValues({});
    setGapOtherMode(false);
    setGapFollowUpQuestion("");
    setGapFollowUpSlots([]);
    setGapFollowUpQuestionId("");
    return true;
  }

  function languageScoreFormQuestion(
    parentQuestion: GapQuestion,
    selection: SelectedLanguageTest,
  ): { question: GapQuestion; need: GapEvidenceNeed; prompt: string } | null {
    const { needs } = currentGapEvidenceContext(parentQuestion);
    const need = needs.find((item) => item.key.toLowerCase() === selection.evidenceKey);
    if (!need || need.evidence_type !== "language_score") return null;
    const standardPaths = selection.evidenceKey === "ielts"
      ? ["score", "listening", "reading", "writing", "speaking"]
      : ["score", "reading", "listening", "speaking", "writing"];
    const existing = userEvidence.find((item) => (
      item.key.toLowerCase() === selection.evidenceKey
      && item.availability === "known"
    ));
    const existingValue = existing?.value && typeof existing.value === "object"
      ? existing.value as Record<string, unknown>
      : {};
    const existingSubscores = existingValue.subscores && typeof existingValue.subscores === "object"
      ? existingValue.subscores as Record<string, unknown>
      : {};
    const paths = standardPaths.filter((path) => (
      path === "score"
        ? existingValue.score == null
        : existingSubscores[path] == null
    ));
    const labels: Record<string, string> = {
      score: "Overall / Total",
      listening: "Listening",
      reading: "Reading",
      writing: "Writing",
      speaking: "Speaking",
    };
    const thresholdLabel = (path: string) => {
      const threshold = path === "score" ? need.minimum : need.component_minimum;
      return threshold == null ? "" : `（项目要求 ≥ ${threshold}）`;
    };
    const prompt = `请填写你的 ${selection.label} 成绩。`;
    return {
      need,
      prompt,
      question: {
        ...parentQuestion,
        question: prompt,
        prompt,
        evidence_keys: [need.key],
        expected_evidence_keys: [need.key],
        allowed_evidence_keys: [need.key],
        control_type: "number_group",
        options: [],
        fields: paths.map((path) => ({
          field_id: `${selection.evidenceKey}-${path}`,
          label: `${labels[path]}${thresholdLabel(path)}`,
          evidence_key: need.key,
          value_path: path,
          required: true,
          placeholder: null,
        })),
        validation: {
          required: true,
          minimum: null,
          maximum: null,
          step: null,
          min_selections: null,
          max_selections: null,
        },
        allow_unknown: true,
        allow_negative: true,
        allow_other: false,
        schema_status: "valid",
        schema_error_code: null,
      },
    };
  }

  function displayedGapQuestion(question: GapQuestion): string {
    if (selectedLanguageTest?.questionId === question.question_id) {
      return `请填写你的 ${selectedLanguageTest.label} 成绩。`;
    }
    return gapFollowUpQuestionId === question.question_id && gapFollowUpQuestion
      ? gapFollowUpQuestion
      : question.question;
  }

  function renderStructuredGapControl(question: GapQuestion) {
    const allowedEvidenceKeys = (question.allowed_evidence_keys ?? []).length > 0
      ? question.allowed_evidence_keys
      : question.expected_evidence_keys;
    const hasActiveFollowUp = gapFollowUpQuestionId === question.question_id && gapFollowUpSlots.length > 0;
    const activeEvidenceKeys = hasActiveFollowUp
      ? allowedEvidenceKeys.filter((key) => gapFollowUpSlots.some((slot) => slot.startsWith(`${key}.`)))
      : question.expected_evidence_keys;
    const visibleFields = hasActiveFollowUp
      ? question.fields.filter((field) => gapFollowUpSlots.includes(`${field.evidence_key}.${field.value_path}`))
      : question.fields;
    const visibleOptions = question.options.filter((option) => !option.evidence_key || activeEvidenceKeys.includes(option.evidence_key));
    const structuredDisabled = isParsingGapAnswer || isAnalyzingGap;
    const activeLanguageForm = selectedLanguageTest?.questionId === question.question_id
      ? languageScoreFormQuestion(question, selectedLanguageTest)
      : null;
    if (activeLanguageForm) {
      const scoreQuestion = activeLanguageForm.question;
      const completed = scoreQuestion.fields.every((field) => (
        gapStructuredValues[field.field_id] !== undefined
        && gapStructuredValues[field.field_id] !== ""
      ));
      const summary = scoreQuestion.fields
        .filter((field) => gapStructuredValues[field.field_id] !== undefined)
        .map((field) => `${field.label}: ${String(gapStructuredValues[field.field_id])}`)
        .join("；");
      return <div className={styles.structuredComposer}>
        <div className={styles.structuredFields}>{scoreQuestion.fields.map((field) => <label key={field.field_id}><span>{field.label}</span><input type="number" step="any" value={String(gapStructuredValues[field.field_id] ?? "")} disabled={structuredDisabled} onChange={(event) => setGapStructuredValues((current) => { const next = { ...current }; if (!event.target.value) delete next[field.field_id]; else next[field.field_id] = Number(event.target.value); return next; })} /></label>)}</div>
        <button type="button" className={styles.structuredSubmit} disabled={!completed || structuredDisabled} onClick={() => void submitStructuredGapAnswer({ values: gapStructuredValues }, summary, scoreQuestion, activeLanguageForm.prompt)}>提交成绩</button>
        <div className={styles.gapQuickAnswers}>
          <button type="button" disabled={structuredDisabled} onClick={() => void submitStructuredGapAnswer({ terminal_state: "known_negative" }, "暂时没有", scoreQuestion, activeLanguageForm.prompt)}>暂时没有</button>
          <button type="button" disabled={structuredDisabled} onClick={() => void submitStructuredGapAnswer({ terminal_state: "unknown" }, "不确定", scoreQuestion, activeLanguageForm.prompt)}>不确定</button>
        </div>
      </div>;
    }
    const answerSummary = () => {
      if (question.control_type === "single_select" || question.control_type === "multi_select") {
        return visibleOptions.filter((option) => gapSelectedOptions.includes(option.value)).map((option) => option.label).join("；");
      }
      return visibleFields
        .filter((field) => gapStructuredValues[field.field_id] !== undefined && gapStructuredValues[field.field_id] !== "")
        .map((field) => `${field.label}: ${String(gapStructuredValues[field.field_id])}`)
        .join("；");
    };

    const hasVisibleStructuredPath = question.control_type === "single_select" || question.control_type === "multi_select"
      ? visibleOptions.length > 0
      : visibleFields.length > 0;
    if (question.schema_status !== "valid" || question.control_type === "text_fallback" || hasActiveFollowUp && !hasVisibleStructuredPath) {
      return <div className={`${styles.discoveryNotice} ${styles.discoveryError}`}><p>这个问题暂时无法生成，请重新尝试。</p><button type="button" disabled={isRepairingGapQuestion} onClick={() => void regenerateGapQuestion(question)}>{isRepairingGapQuestion ? "正在重新生成…" : "重新生成问题"}</button></div>;
    }

    if (gapOtherMode) {
      return <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void submitGapAnswer(gapInput); }}>
        <label htmlFor="gap-answer">你的回答</label>
        <div className={styles.inputShell}><textarea id="gap-answer" rows={2} value={gapInput} disabled={structuredDisabled} onChange={(event) => setGapInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitGapAnswer(gapInput); } }} placeholder="可以直接回答，也可以说不知道、不记得或暂时没有" /><button type="submit" disabled={!gapInput.trim() || structuredDisabled} aria-label="发送回答">↑</button></div>
        <div className={styles.gapQuickAnswers}><button type="button" onClick={() => void submitGapAnswer("不知道，暂时无法提供")}>不知道</button><button type="button" onClick={() => void submitGapAnswer("暂时没有")}>暂时没有</button></div>
      </form>;
    }

    return <div className={styles.structuredComposer}>
      {question.control_type === "experience_form" && (() => {
        const typeOptions = visibleOptions.filter((option) => option.value.startsWith("experience:"));
        const unitOptions = visibleOptions.filter((option) => option.value.startsWith("unit:"));
        const noneSelected = gapSelectedOptions.includes("experience:none");
        const selectedTypes = gapSelectedOptions.filter((value) => value.startsWith("experience:") && value !== "experience:none");
        const selectedUnit = gapSelectedOptions.find((value) => value.startsWith("unit:"));
        const needsDuration = visibleFields.some((field) => field.field_id === "experience-duration");
        const typeComplete = typeOptions.length === 0 || noneSelected || selectedTypes.length > 0;
        const durationComplete = noneSelected || !needsDuration || (
          gapStructuredValues["experience-duration"] !== undefined && Boolean(selectedUnit)
        );
        const toggleType = (value: string) => {
          if (value === "experience:none") {
            setGapSelectedOptions([value]);
            setGapStructuredValues((current) => {
              const next = { ...current };
              delete next["experience-duration"];
              return next;
            });
            return;
          }
          setGapSelectedOptions((current) => {
            const withoutNone = current.filter((item) => item !== "experience:none");
            return withoutNone.includes(value)
              ? withoutNone.filter((item) => item !== value)
              : [...withoutNone, value];
          });
        };
        const chooseUnit = (value: string) => setGapSelectedOptions((current) => [
          ...current.filter((item) => !item.startsWith("unit:") && item !== "experience:none"),
          value,
        ]);
        const summary = [
          ...typeOptions.filter((option) => gapSelectedOptions.includes(option.value)).map((option) => option.label),
          ...(noneSelected ? [] : unitOptions.filter((option) => gapSelectedOptions.includes(option.value)).map((option) => option.label)),
          ...(noneSelected || gapStructuredValues["experience-duration"] === undefined ? [] : [`累计 ${String(gapStructuredValues["experience-duration"])}`]),
        ].join("；");
        return <>
          {typeOptions.length > 0 && <div className={styles.structuredOptions}>{typeOptions.map((option) => {
            const selected = gapSelectedOptions.includes(option.value);
            return <button type="button" key={option.value} className={selected ? styles.selectedStructuredOption : ""} disabled={structuredDisabled} onClick={() => toggleType(option.value)}>{selected ? "✓ " : ""}{option.label}</button>;
          })}</div>}
          {!noneSelected && needsDuration && <>
            <div className={styles.structuredFields}><label><span>累计时长</span><input type="number" min={0} step="any" value={String(gapStructuredValues["experience-duration"] ?? "")} disabled={structuredDisabled} onChange={(event) => setGapStructuredValues((current) => { const next = { ...current }; if (!event.target.value) delete next["experience-duration"]; else next["experience-duration"] = Number(event.target.value); return next; })} /></label></div>
            <div className={styles.structuredOptions}>{unitOptions.map((option) => {
              const selected = gapSelectedOptions.includes(option.value);
              return <button type="button" key={option.value} className={selected ? styles.selectedStructuredOption : ""} disabled={structuredDisabled} onClick={() => chooseUnit(option.value)}>{selected ? "✓ " : ""}{option.label}</button>;
            })}</div>
          </>}
          <button type="button" className={styles.structuredSubmit} disabled={!typeComplete || !durationComplete || structuredDisabled} onClick={() => void submitStructuredGapAnswer({ selected_options: gapSelectedOptions, values: gapStructuredValues }, summary)}>提交</button>
        </>;
      })()}
      {question.control_type === "boolean_group" && <>
        <div className={styles.structuredFields}>{visibleFields.map((field) => {
          const value = gapStructuredValues[field.field_id];
          return <div key={field.field_id}>
            <span>{field.label}</span>
            <div className={styles.structuredOptions}>
              <button type="button" className={value === true ? styles.selectedStructuredOption : ""} disabled={structuredDisabled} onClick={() => setGapStructuredValues((current) => ({ ...current, [field.field_id]: true }))}>{value === true ? "✓ " : ""}有</button>
              <button type="button" className={value === false ? styles.selectedStructuredOption : ""} disabled={structuredDisabled} onClick={() => setGapStructuredValues((current) => ({ ...current, [field.field_id]: false }))}>{value === false ? "✓ " : ""}没有</button>
            </div>
          </div>;
        })}</div>
        <button type="button" className={styles.structuredSubmit} disabled={Object.keys(gapStructuredValues).length === 0 || structuredDisabled} onClick={() => void submitStructuredGapAnswer({ values: gapStructuredValues }, answerSummary())}>提交</button>
      </>}
      {question.control_type === "boolean" && <div className={styles.structuredOptions}>
        <button type="button" disabled={structuredDisabled} onClick={() => { const field = visibleFields[0]; if (field) void submitStructuredGapAnswer({ values: { [field.field_id]: true } }, "有"); }}>有 / 是</button>
        <button type="button" disabled={structuredDisabled} onClick={() => { const field = visibleFields[0]; if (field) void submitStructuredGapAnswer({ values: { [field.field_id]: false } }, "没有 / 否"); }}>没有 / 否</button>
      </div>}
      {(question.control_type === "single_select" || question.control_type === "multi_select") && <>
        <div className={styles.structuredOptions}>{visibleOptions.map((option) => {
          const selected = gapSelectedOptions.includes(option.value);
          return <button type="button" key={option.value} className={selected ? styles.selectedStructuredOption : ""} disabled={structuredDisabled} onClick={() => setGapSelectedOptions((current) => question.control_type === "single_select" ? [option.value] : selected ? current.filter((value) => value !== option.value) : [...current, option.value])}>{selected ? "✓ " : ""}{option.label}</button>;
        })}</div>
        <button type="button" className={styles.structuredSubmit} disabled={gapSelectedOptions.length === 0 || structuredDisabled} onClick={() => {
          const selectedOption = visibleOptions.find((option) => gapSelectedOptions.includes(option.value));
          if (question.control_type === "single_select" && selectedOption && beginLanguageScoreForm(question, selectedOption)) return;
          void submitStructuredGapAnswer({ selected_options: gapSelectedOptions }, answerSummary());
        }}>提交</button>
      </>}
      {(question.control_type === "number" || question.control_type === "number_group" || question.control_type === "date") && <>
        <div className={styles.structuredFields}>{visibleFields.map((field) => <label key={field.field_id}><span>{field.label}</span><input type={question.control_type === "date" ? "date" : "number"} min={question.validation.minimum ?? undefined} max={question.validation.maximum ?? undefined} step={question.validation.step ?? "any"} placeholder={field.placeholder ?? undefined} value={String(gapStructuredValues[field.field_id] ?? "")} disabled={structuredDisabled} onChange={(event) => setGapStructuredValues((current) => { const next = { ...current }; if (!event.target.value) delete next[field.field_id]; else next[field.field_id] = question.control_type === "date" ? event.target.value : Number(event.target.value); return next; })} /></label>)}</div>
        <button type="button" className={styles.structuredSubmit} disabled={Object.keys(gapStructuredValues).length === 0 || structuredDisabled} onClick={() => void submitStructuredGapAnswer({ values: gapStructuredValues }, answerSummary())}>提交</button>
      </>}
      {question.control_type === "short_text" && <>
        <div className={styles.structuredFields}>{visibleFields.map((field) => <label key={field.field_id}><span>{field.label}</span><input type="text" maxLength={200} placeholder={field.placeholder ?? undefined} value={String(gapStructuredValues[field.field_id] ?? "")} disabled={structuredDisabled} onChange={(event) => setGapStructuredValues((current) => { const next = { ...current }; const value = event.target.value; if (!value) delete next[field.field_id]; else next[field.field_id] = value; return next; })} /></label>)}</div>
        <button type="button" className={styles.structuredSubmit} disabled={Object.keys(gapStructuredValues).length === 0 || structuredDisabled} onClick={() => void submitStructuredGapAnswer({ values: gapStructuredValues }, answerSummary())}>提交</button>
      </>}
      <div className={styles.gapQuickAnswers}>
        {question.allow_unknown && <button type="button" disabled={structuredDisabled} onClick={() => void submitStructuredGapAnswer({ terminal_state: "unknown" }, "不确定 / 不记得")}>不确定 / 不记得</button>}
        {question.allow_negative && <button type="button" disabled={structuredDisabled} onClick={() => void submitStructuredGapAnswer({ terminal_state: "known_negative" }, "暂时没有")}>暂时没有</button>}
        {question.allow_other && <button type="button" disabled={structuredDisabled} onClick={() => setGapOtherMode(true)}>其他 / 补充说明</button>}
      </div>
    </div>;
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

  useEffect(() => {
    if (targetStep !== "explore" || rankingBasis !== "subject" || qsSubjects.length > 0) return;
    let cancelled = false;
    setIsLoadingSubjects(true);
    setSubjectListError("");
    void fetch(`${API_BASE_URL}/rankings/qs/subjects`)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "QS 学科列表加载失败");
        if (!cancelled) setQsSubjects((data as QSSubjectListResponse).subjects);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSubjectListError(error instanceof Error ? error.message : "QS 学科列表加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoadingSubjects(false);
      });
    return () => {
      cancelled = true;
    };
  }, [qsSubjects.length, rankingBasis, targetStep]);

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
    if (rankingBasis === "subject" && !selectedSubject && !subjectUncertain) {
      setCandidateUniversities([]);
      return;
    }

    const useSubjectRanking = rankingBasis === "subject" && Boolean(selectedSubject);

    const nextTarget: ExploreTarget = {
      mode: "explore",
      countries,
      target_major: targetMajor.trim(),
      ranking: { type: "QS", basis: useSubjectRanking ? "subject" : "overall", min: minimum, max: maximum },
      ranking_subject_id: useSubjectRanking ? selectedSubjectId : null,
      ranking_subject: useSubjectRanking ? selectedSubject : null,
      additional_preferences: additionalPreferences.trim(),
    };
    const timer = window.setTimeout(() => {
      setTarget(nextTarget);
      void discoverUniversities(nextTarget);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [additionalPreferences, countries, discoverUniversities, rankingBasis, rankingMax, rankingMin, selectedSubject, selectedSubjectId, subjectUncertain, targetMajor, targetStep]);

  if (!profileHydrated) {
    return <main className={styles.page}><header className={styles.header}><div className={styles.brand}><span className={styles.brandMark}>知</span><span>知途留学</span></div><span className={styles.status}>正在读取背景信息…</span></header></main>;
  }

  function persistReusableEvidence(nextEvidence: UserEvidence[]) {
    setUserEvidence(nextEvidence);
    writeReusableEvidence(window.localStorage, nextEvidence);
  }

  if (showProfile && targetStep) {
    return (
      <main className={`${styles.page} ${styles.targetPage}`}>
        <header className={styles.header}><div className={styles.brand}><span className={styles.brandMark}>知</span><span>知途留学</span></div><span className={styles.status}>{targetStep === "planning" ? "06 · Planning Workflow" : targetStep === "gap_results" ? "05 · Gap Table" : targetStep === "special_interview" ? "04 · 项目特殊要求" : targetStep === "requirements" ? "03 · 申请要求分析" : targetStep === "entry_cycle" ? "02 · 目标申请周期" : "02 · 目标院校与申请范围"}</span></header>
        <section className={styles.targetShell}>
          <div className={styles.moduleProgress}><span className={profileStatus === "completed" ? styles.moduleDone : styles.moduleSkipped}>{profileStatus === "completed" ? "✓ 基础信息" : "基础信息已跳过"}</span><i /><span className={targetStep === "explore" || targetStep === "entry_cycle" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "explore" ? "2 目标范围" : targetStep === "entry_cycle" ? "2 申请周期" : "✓ 目标项目"}</span>{targetStep !== "explore" && targetStep !== "entry_cycle" && <><i /><span className={targetStep === "requirements" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "requirements" ? "3 要求确认" : "✓ 要求确认"}</span></>}{(targetStep === "special_interview" || targetStep === "gap_results" || targetStep === "planning") && <><i /><span className={targetStep === "special_interview" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "special_interview" ? "4 项目特殊要求" : "✓ 项目特殊要求"}</span></>}{(targetStep === "gap_results" || targetStep === "planning") && <><i /><span className={targetStep === "gap_results" ? styles.moduleCurrent : styles.moduleDone}>{targetStep === "gap_results" ? "5 Gap Table" : "✓ Gap Table"}</span></>}{targetStep === "planning" && <><i /><span className={styles.moduleCurrent}>6 行动计划</span></>}</div>

          {targetStep === "explore" && <>
            <button type="button" className={styles.backButton} onClick={returnToProfile}>← {profileStatus === "completed" ? "返回基础信息" : "补充基础信息"}</button>
            <div className={styles.exploreHeading}><div><p className={styles.eyebrow}>GLOBAL UNIVERSITY EXPLORER</p><h1>探索目标院校</h1></div><p>筛选条件变化后院校会实时更新；相关项目仅在你点击院校后检索。</p></div>
            <div className={styles.exploreWorkspace}>
              <section className={`${styles.targetForm} ${styles.exploreFilters}`}>
                <fieldset><legend>目标国家 / 地区 <small>可多选</small></legend><div className={styles.chipGrid}>{COUNTRY_OPTIONS.map((country) => <button key={country} type="button" className={countries.includes(country) ? styles.selectedChip : ""} onClick={() => toggleCountry(country)}>{countries.includes(country) ? "✓ " : "+ "}{country}</button>)}</div>{!countries.length && <span className={styles.fieldHint}>未选择时显示全球院校</span>}</fieldset>
                <div className={styles.filterRow}><label><span>目标专业</span><input value={targetMajor} onChange={(event) => { setTargetMajor(event.target.value); setCandidateUniversities([]); }} placeholder="例如：人工智能、计算机科学" /></label><label><span>榜单类型</span><input value="QS World University Rankings" readOnly aria-readonly="true" /></label></div>
                <fieldset className={styles.rankingBasis}><legend>QS 排名依据</legend><div><button type="button" className={rankingBasis === "overall" ? styles.selectedBasis : ""} onClick={() => { setRankingBasis("overall"); setCandidateUniversities([]); setDiscoveryError(""); }}><strong>按学校综合排名筛选</strong><span>QS World University Rankings · 2027</span><small>看整所大学的综合实力</small></button><button type="button" className={rankingBasis === "subject" ? styles.selectedBasis : ""} onClick={() => { setRankingBasis("subject"); setSubjectUncertain(false); setCandidateUniversities([]); setDiscoveryError(""); }}><strong>按目标学科排名筛选</strong><span>QS World University Rankings by Subject · 2026</span><small>直接选择 QS 官方学科分类</small></button></div>{rankingBasis === "subject" && (selectedSubject || subjectUncertain) && <p className={styles.currentRankingSubject}><span>当前 QS Subject</span><strong>{subjectUncertain ? "暂不确定 · 当前按综合排名筛选" : selectedSubject}</strong></p>}</fieldset>
                {rankingBasis === "subject" && <div className={styles.subjectMapper}>
                  <div><span>选择 QS Subject</span><p>选项直接来自后端当前支持的 QS 学科列表；选择后仅查询本地 QS 数据。</p></div>
                  <label className={styles.subjectCombobox}><span>搜索或选择学科</span><input list="qs-subject-options" value={subjectSearch} onChange={(event) => { const value = event.target.value; const match = qsSubjects.find((subject) => subject.subject_name === value); setSubjectSearch(value); setSelectedSubject(match?.subject_name ?? ""); setSelectedSubjectId(match?.subject_id ?? ""); setSubjectUncertain(false); setCandidateUniversities([]); }} placeholder={isLoadingSubjects ? "正在加载 QS 学科…" : "输入关键词，例如 Computer Science"} disabled={isLoadingSubjects} /><datalist id="qs-subject-options">{qsSubjects.map((subject) => <option key={subject.subject_id} value={subject.subject_name} />)}</datalist></label>
                  <button type="button" onClick={() => { setSubjectUncertain(true); setSubjectSearch(""); setSelectedSubject(""); setSelectedSubjectId(""); setCandidateUniversities([]); }}>暂不确定</button>
                  {subjectSearch && !selectedSubject && !subjectUncertain && <p className={styles.subjectHint}>请从下拉列表中选择一个完整的 QS Subject。</p>}
                  {subjectListError && <p className={styles.subjectError}>{subjectListError}</p>}
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
            <div className={styles.requirementsHeading}><div><p className={styles.eyebrow}>REQUIREMENTS REVIEW</p><h1>目标项目申请要求</h1><p>AI 根据公开网页整理，仅供参考；最终申请要求以院校最新官方信息为准。</p>{requirementsReview?.checked_at && <p>申请信息最后获取：{requirementsReview.checked_at.slice(0, 10)}</p>}</div><div className={styles.requirementsHeadingActions}><button type="button" onClick={() => setTargetStep("explore")}>← 返回院校筛选</button><button type="button" onClick={() => { void retrieveRequirements(activeTargetProgram, true); void retrieveTimeline(activeTargetProgram, true); }} disabled={isLoadingRequirements || isLoadingTimeline}>重新获取最新信息</button><a href={activeTargetProgram.official_program_url} target="_blank" rel="noopener noreferrer">查看项目官网 ↗</a></div></div>
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

          {targetStep === "special_interview" && activeTargetProgram && specialInterviewPlan && <SpecialRequirementInterview
            university={activeTargetProgram.university}
            program={activeTargetProgram.program}
            plan={specialInterviewPlan}
            submitting={isSubmittingSpecialInterview}
            error={gapError}
            onSubmit={(answers) => void submitSpecialInterview(answers)}
          />}

          {targetStep === "gap_interview" && activeTargetProgram && gapPlan && <div className={styles.gapInterviewStage}>
            <div className={styles.gapInterviewHeading}><p className={styles.eyebrow}>ADAPTIVE GAP INTERVIEW</p><h1>补充匹配信息</h1><p>我会根据当前项目的实际申请要求，只询问完成匹配分析所需要的信息，不会重复询问已经提供过的内容。</p><div><strong>{activeTargetProgram.university}</strong><span>{activeTargetProgram.program}</span></div></div>
            <div className={styles.gapInterviewMeta}><span>还需补充 <strong>{Math.max(gapPlan.questions.length - gapQuestionIndex, 0)}</strong> 项信息</span><span>已复用 {gapPlan.reusable_evidence.length} 项已有证据</span></div>
            <div className={styles.gapChat}>
              <div className={styles.messages} aria-live="polite">
                {gapTurns.map((turn, index) => <div key={`${turn.question}-${index}`}><div className={styles.assistantRow}><div className={styles.miniAvatar}>知</div><p>{turn.question}</p></div><div className={styles.userRow}><p>{turn.answer}</p></div></div>)}
                {!isAnalyzingGap && gapPlan.questions[gapQuestionIndex] && <div className={styles.assistantRow}><div className={styles.miniAvatar}>知</div><p>{displayedGapQuestion(gapPlan.questions[gapQuestionIndex])}</p></div>}
                {isAnalyzingGap && <div className={`${styles.assistantRow} ${styles.thinkingRow}`}><div className={styles.miniAvatar}>知</div><p><span>●</span><span>●</span><span>●</span> 正在生成 Gap Table</p></div>}
                {gapError && <div className={styles.inlineError}>{gapError}</div>}
              </div>
              {gapPlan.questions[gapQuestionIndex] && renderStructuredGapControl(gapPlan.questions[gapQuestionIndex])}
            </div>
          </div>}

          {targetStep === "gap_results" && activeTargetProgram && gapAnalysis && <div className={styles.gapResultsStage}>
            <div className={styles.gapResultsHeading}><div><p className={styles.eyebrow}>GAP TABLE</p><h1>申请匹配结果</h1><p>{activeTargetProgram.university} · {activeTargetProgram.program}</p></div><button type="button" className={styles.backButton} onClick={() => setTargetStep("requirements")}>返回查看申请要求</button></div>
            <div className={styles.gapSummary}>{(["met", "partial", "not_met", "unknown"] as GapStatus[]).map((status) => <div key={status}><span>{status === "met" ? "满足" : status === "partial" ? "部分满足" : status === "not_met" ? "未满足" : "信息不足"}</span><strong>{gapAnalysis.results.filter((item) => item.status === status).length}</strong></div>)}</div>
            <div className={styles.gapTableWrap}><table className={styles.gapTable}><thead><tr><th>目标要求</th><th>类型</th><th>匹配状态</th><th>用户证据</th><th>差距</th><th>来源</th></tr></thead><tbody>{gapAnalysis.results.map((result) => <tr key={result.requirement_id}><td><strong>{result.requirement}</strong>{result.requirement_zh && <span className={styles.gapRequirementTranslation}>{result.requirement_zh}</span>}<small>{result.reason}</small></td><td>{REQUIREMENT_CATEGORIES.find((item) => item.id === result.category)?.label ?? result.category}</td><td><span className={result.status === "met" ? styles.gapStatusMet : result.status === "partial" ? styles.gapStatusPartial : result.status === "not_met" ? styles.gapStatusNotMet : styles.gapStatusUnknown}>{gapStatusLabel(result)}</span></td><td>{result.user_evidence}</td><td>{result.gap}</td><td><div>{result.requirement_verification_status === "user_supplied" ? "用户补充要求" : result.requirement_verification_status === "model_memory_unverified" ? "AI 参考 · 当前未确认官方来源" : result.source_url ? <a href={result.source_url} target="_blank" rel="noopener noreferrer">官网来源 ↗</a> : "AI 检索自官网"}</div><small>{TEMPORAL_APPLICABILITY_LABELS[result.temporal_applicability]}{result.source_cycle ? ` · ${result.source_cycle}` : ""}{result.temporal_note ? `：${result.temporal_note}` : ""}</small></td></tr>)}</tbody></table></div>
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
            {actionPlan.needs_confirmation.length > 0 && <section className={styles.planningDisposition}><strong>需要确认</strong>{actionPlan.needs_confirmation.map((item) => <article key={item.source_gap_id}><h2>{item.title}</h2><p>{item.reason}</p></article>)}</section>}
            {actionPlan.eligibility_risks.length > 0 && <section className={`${styles.planningDisposition} ${styles.planningRisk}`}><strong>资格风险</strong>{actionPlan.eligibility_risks.map((item) => <article key={item.source_gap_id}><h2>{item.title}</h2><p>{item.reason}</p></article>)}</section>}
            {actionPlan.actions.length === 0 && actionPlan.needs_confirmation.length === 0 && actionPlan.eligibility_risks.length === 0 ? <div className={styles.actionPlanEmpty}>当前所有可匹配要求均已满足，无需生成额外任务。</div> : actionPlan.actions.length > 0 && <div className={styles.unifiedTimeline}>
              {groupPlanningActions(actionPlan.actions).map((group) => <section key={group.timePeriod} className={styles.actionPeriod}>
                <div className={styles.actionPeriodLabel}><span /> <strong>{planningDisplayText(group.timePeriod, actionPlan.deadline_is_precise)}</strong></div>
                <div className={styles.actionPeriodItems}>{group.items.map((action) => <article key={action.action_id} className={action.plan_track === "optional" ? styles.optionalAction : styles.mainAction}>
                  <div className={styles.actionCardTop}><span>{action.timing_status === "urgent" ? "紧急" : `优先 ${action.priority_order}`}</span>{action.target_date && <time>{action.target_date}</time>}</div>
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

  return <StandardProfileInterview profile={profile} profileStatus={profileStatus} entryView={profileEntryView} onDraftChange={updateProfileDraft} onSave={persistProfile} onExplore={continueToExplore} />;
}
