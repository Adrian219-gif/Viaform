from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Type, TypeVar, get_args
from urllib.parse import urljoin, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .programme_cache import (
    CacheSource,
    ProgrammePoolRecord,
    ProgrammeCache,
    normalized_programme_identity,
    programme_cache_key,
    programme_semantic_cache_key,
    university_cache_key,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

QS_RANKINGS_DB = BACKEND_DIR / "data" / "rankings" / "qs_rankings.sqlite"
QS_SUBJECTS_FILE = BACKEND_DIR / "data" / "rankings" / "qs_subjects.json"
TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS = 30.0
# Preserve the full 180s Search budget plus a bounded 180s envelope for the
# existing sequential official-page fallback and response processing.
REQUIREMENTS_TOTAL_TIMEOUT_SECONDS = 360.0
TIMELINE_TOTAL_TIMEOUT_SECONDS = 120.0
WEB_SEARCH_TIMEOUT_SECONDS = 180.0
OFFICIAL_PROGRAM_PAGE_TIMEOUT_SECONDS = 30.0
OFFICIAL_PROGRAM_PAGE_MAX_CHARS = 120_000
OFFICIAL_PROGRAM_PAGE_MAX_REDIRECTS = 3
SCHOOL_URL_BATCH_SIZE = 12
PROGRAMME_CACHE = ProgrammeCache(
    runtime_db=BACKEND_DIR / "data" / "runtime" / "programme_cache.sqlite",
    seed_dir=BACKEND_DIR / "data" / "seed" / "programme_cache",
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
GAP_PLANNER_INITIAL_MAX_OUTPUT_TOKENS = 10_000
GAP_PLANNER_RETRY_MAX_OUTPUT_TOKENS = 12_000

logger = logging.getLogger(__name__)


class InterviewAnswer(BaseModel):
    question: str
    answer: str


class ProfileRequest(BaseModel):
    answers: List[InterviewAnswer] = Field(min_length=6, max_length=6)


class ScoreWithScale(BaseModel):
    value: Optional[float] = None
    scale: Optional[float] = None


class Education(BaseModel):
    university: str = ""
    major: str = ""
    gpa: Optional[ScoreWithScale] = None
    average_score: Optional[ScoreWithScale] = None
    courses: List[str] = Field(default_factory=list)


class Experience(BaseModel):
    projects: List[str] = Field(default_factory=list)
    research: List[str] = Field(default_factory=list)
    internship: List[str] = Field(default_factory=list)
    work: List[str] = Field(default_factory=list)
    project_status: Optional[Literal["has_value", "none", "unknown"]] = None
    research_status: Optional[Literal["has_value", "none", "unknown"]] = None
    internship_status: Optional[Literal["has_value", "none", "unknown"]] = None
    work_status: Optional[Literal["has_value", "none", "unknown"]] = None


FieldInformationState = Literal["known", "unavailable", "missing"]


class Language(BaseModel):
    IELTS: Optional[float] = None
    TOEFL: Optional[float] = None
    IELTS_status: Optional[Literal["has_value", "none", "unknown"]] = None
    TOEFL_status: Optional[Literal["has_value", "none", "unknown"]] = None
    IELTS_subscores: Dict[str, Optional[float]] = Field(
        default_factory=lambda: {
            "listening": None, "reading": None, "writing": None, "speaking": None,
        }
    )
    TOEFL_subscores: Dict[str, Optional[float]] = Field(
        default_factory=lambda: {
            "reading": None, "listening": None, "speaking": None, "writing": None,
        }
    )


class StandardizedTest(BaseModel):
    GRE: Optional[float] = None
    GMAT: Optional[float] = None
    GRE_status: Optional[Literal["has_value", "none", "unknown"]] = None
    GMAT_status: Optional[Literal["has_value", "none", "unknown"]] = None


class ApplicationMaterials(BaseModel):
    cv_status: Optional[Literal["prepared", "not_prepared", "unknown", "not_applicable"]] = None
    transcript_status: Optional[Literal["prepared", "not_prepared", "unknown", "not_applicable"]] = None
    degree_certificate_status: Optional[Literal["prepared", "not_prepared", "unknown", "not_applicable"]] = None
    motivation_letter_status: Optional[Literal["prepared", "not_prepared", "unknown", "not_applicable"]] = None
    portfolio_status: Optional[Literal["prepared", "not_prepared", "unknown", "not_applicable"]] = None
    confirmed_recommenders: Optional[int] = Field(default=None, ge=0)


class UserProfile(BaseModel):
    education: Education = Field(default_factory=Education)
    experience: Experience = Field(default_factory=Experience)
    language: Language = Field(default_factory=Language)
    standardized_test: StandardizedTest = Field(default_factory=StandardizedTest)
    materials: ApplicationMaterials = Field(default_factory=ApplicationMaterials)


TopicName = Literal[
    "education",
    "courses",
    "projects_research",
    "internship",
    "language",
    "standardized_test",
]


class TopicTurnRequest(BaseModel):
    topic: TopicName
    answers: List[InterviewAnswer] = Field(min_length=1)
    profile: UserProfile = Field(default_factory=UserProfile)
    follow_up_count: int = Field(default=0, ge=0, le=2)


class TopicAnalysis(BaseModel):
    profile: UserProfile
    answer_state: Literal["valid", "explicit_none", "ambiguous"]
    topic_complete: bool
    field_states: Dict[str, FieldInformationState] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    follow_up_question: str = ""


class TopicTurnResponse(BaseModel):
    profile: UserProfile
    complete: bool
    limit_reached: bool
    field_states: Dict[str, FieldInformationState] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    follow_up_question: str = ""


class RankingScope(BaseModel):
    type: Literal["QS"]
    basis: Literal["overall", "subject"] = "overall"
    min: int = Field(ge=1)
    max: int = Field(ge=1)


class ExploreTargetRequest(BaseModel):
    mode: Literal["explore"]
    countries: List[str] = Field(default_factory=list)
    target_major: str = ""
    ranking: RankingScope
    ranking_subject_id: Optional[str] = None
    ranking_subject: Optional[str] = None
    additional_preferences: str = ""


class RankedUniversity(BaseModel):
    university: str
    country: str
    ranking: int
    source_url: str


class RankedUniversityResult(BaseModel):
    universities: List[RankedUniversity] = Field(default_factory=list)


class LatestQSEdition(BaseModel):
    ranking_edition: Optional[int] = None
    ranking_source_url: str = ""


class CandidateProgram(BaseModel):
    university: str
    program: str
    country: str
    ranking: Optional[int] = None
    ranking_system: Literal["QS"] = "QS"
    ranking_edition: int
    ranking_source_url: str
    official_program_url: str
    degree_type: str = ""
    relevance_reason: str = ""


class CandidateProgramResult(BaseModel):
    candidates: List[CandidateProgram] = Field(default_factory=list)
    cache_source: Literal["live", "programme_pool"] = "live"
    refresh_scheduled: bool = False


class WebSearchProgramCandidate(BaseModel):
    program: str = Field(min_length=1)
    official_program_url: str = Field(min_length=1)
    degree_type: str = ""
    relevance_reason: str = ""


class ProgramDiscoveryWebSearchOutput(BaseModel):
    programs: List[WebSearchProgramCandidate] = Field(default_factory=list, max_length=5)


class SchoolOfficialUrl(BaseModel):
    index: int = Field(ge=0)
    school_official_url: Optional[str] = None


class SchoolOfficialUrlOutput(BaseModel):
    schools: List[SchoolOfficialUrl] = Field(default_factory=list)


class TargetProgramLookupOutput(BaseModel):
    program: str = Field(min_length=1)
    official_program_url: str = Field(min_length=1)


class TargetProgramConfirmationRequest(BaseModel):
    university: str = Field(min_length=1)
    program: str = ""
    official_program_url: str = ""


class TargetProgram(BaseModel):
    university: str
    program: str
    official_program_url: str
    official_domain: str
    confirmation_status: Literal["confirmed"] = "confirmed"
    intended_entry_year: int = Field(
        default_factory=lambda: datetime.now(timezone.utc).year + 1,
        ge=2026,
        le=2100,
    )
    intended_entry_term: Literal["fall", "spring", "summer", "winter"] = "fall"


class ApplicationTimelineRequest(BaseModel):
    university: str = Field(min_length=1)
    program_name: str = Field(min_length=1)
    official_program_url: Optional[str] = None
    intended_entry_year: int = Field(ge=2026, le=2100)
    intended_entry_term: Literal["fall", "spring", "summer", "winter"] = "fall"


class ApplicationDeadline(BaseModel):
    label: str = Field(min_length=1)
    type: str = Field(min_length=1)
    date: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class ApplicationTimeline(BaseModel):
    admission_cycle: str = Field(min_length=1)
    application_open_date: Optional[str] = None
    application_open_source_url: Optional[str] = None
    application_deadlines: List[ApplicationDeadline] = Field(default_factory=list)
    rolling_admission: Optional[bool] = None
    rolling_admission_source_url: Optional[str] = None
    status: Literal["complete", "partial", "not_found"]


RequirementCategory = Literal[
    "academic",
    "course",
    "language",
    "standardized_test",
    "experience",
    "materials",
    "other",
]
RequirementCoverage = Literal[
    "official_verified",
    "model_memory_unverified",
    "user_supplied",
    "not_found",
]
RequirementImportance = Literal["required", "recommended", "preferred", "unknown"]
RequirementSourceLevel = Literal["program", "department", "university", "unknown"]
RequirementSourceType = Literal["official_retrieval", "model_memory", "user_supplied"]
RequirementVerificationStatus = Literal[
    "official_verified",
    "model_memory_unverified",
    "user_supplied",
]
RequirementTemporalApplicability = Literal[
    "target_cycle_confirmed",
    "undated",
    "previous_cycle",
    "not_yet_published",
    "unknown",
]
RequirementApplicabilityStage = Literal[
    "pre_admission",
    "conditional_admission",
    "in_program",
    "informational",
    "unclear",
]

REQUIREMENT_CATEGORIES: List[str] = [
    "academic",
    "course",
    "language",
    "standardized_test",
    "experience",
    "materials",
    "other",
]


class RequirementItem(BaseModel):
    category: RequirementCategory
    requirement: str = Field(min_length=1)
    requirement_zh: Optional[str] = None
    importance: RequirementImportance = "unknown"
    source_level: RequirementSourceLevel
    source_type: RequirementSourceType
    verification_status: RequirementVerificationStatus
    source_url: Optional[str] = None
    source_cycle: Optional[str] = None
    temporal_applicability: RequirementTemporalApplicability
    temporal_note: Optional[str] = None
    applicability_stage: RequirementApplicabilityStage = "pre_admission"

    @field_validator("importance", mode="before")
    @classmethod
    def normalize_importance(cls, value: Any) -> Any:
        if value == "conditional_required":
            logger.warning(
                "requirements_importance_alias value=%r normalized=required",
                value,
            )
            return "required"
        return value


class RequirementsExtraction(BaseModel):
    requirements: List[RequirementItem] = Field(default_factory=list)


class RequirementsSearchAudit(BaseModel):
    search_attempts_completed: int = Field(ge=1, le=2)
    programme_page_checked: bool
    sections_checked: List[str] = Field(default_factory=list)
    programme_page_has_no_extractable_requirements: bool = False
    empty_result_reason: Optional[str] = None


class RequirementsWebSearchOutput(BaseModel):
    requirements: List[RequirementItem] = Field(default_factory=list)
    search_audit: Optional[RequirementsSearchAudit] = None


def normalize_extracted_applicability_stages(
    requirements: List[RequirementItem],
) -> List[RequirementItem]:
    """Never treat a model-omitted admission stage as pre-admission."""
    normalized: List[RequirementItem] = []
    for item in requirements:
        if "applicability_stage" in item.model_fields_set:
            normalized.append(item)
            continue
        logger.warning(
            "requirements_applicability_stage_missing normalized=unclear requirement=%r",
            item.requirement[:160],
        )
        normalized.append(item.model_copy(update={"applicability_stage": "unclear"}))
    return normalized


class RequirementCategoryReview(BaseModel):
    category: RequirementCategory
    coverage: RequirementCoverage
    requirements: List[RequirementItem] = Field(default_factory=list)


class TargetProgramRequirementsReview(BaseModel):
    target_program: TargetProgram
    checked_at: str
    categories: List[RequirementCategoryReview]
    cache_source: CacheSource = "live"


EvidenceAvailability = Literal["known", "known_negative", "unknown"]
EvidenceSlotStatus = Literal["known", "known_negative", "unknown", "missing"]
GapStatus = Literal["met", "partial", "not_met", "unknown"]
ConditionalApplicabilityState = Literal[
    "not_conditional", "active", "inactive", "pending"
]
ApplicationRouteScope = Literal["standard", "special_internal"]
RequirementExclusionReason = Literal["unsupported_special_internal_route"]
GapReasonCode = Literal[
    "matched",
    "partially_matched",
    "requirement_not_met",
    "user_evidence_missing",
    "temporal_unconfirmed",
    "previous_cycle_reference",
    "semantic_evidence_insufficient",
    "conditional_pending",
]
GapMatchStrategy = Literal["deterministic", "semantic", "hybrid"]
GapEvidenceType = Literal[
    "education_university",
    "education_major",
    "academic_score",
    "language_score",
    "standardized_score",
    "courses",
    "material_status",
    "material_quantity",
    "experience",
    "prerequisite_course",
    "user_course",
    "generic",
]
EvidenceValueKind = Literal["categorical", "numeric", "boolean", "text", "date"]
LanguageProofKind = Literal[
    "scored_test",
    "medium_of_instruction",
    "certificate",
    "waiver",
]
GREScoreComponent = Literal["verbal", "quantitative", "analytical_writing"]
ExperienceType = Literal["work", "internship", "research", "project", "other"]
ExperienceDurationUnit = Literal["months", "years"]
OtherCollectionKind = Literal[
    "boolean", "numeric", "single_select", "multi_select", "short_text"
]
StandardMaterialType = Literal[
    "cv",
    "transcript",
    "personal_statement",
    "portfolio",
    "degree_certificate",
    "identification",
    "recommendation_letters",
]
GapConstraintKind = Literal[
    "score",
    "material_boolean",
    "material_quantity",
    "experience_duration",
    "course_credit",
    "none",
]


class UserEvidence(BaseModel):
    evidence_type: GapEvidenceType
    key: str = Field(min_length=1)
    value: Any = None
    raw_answer: str = ""
    availability: EvidenceAvailability
    updated_at: str
    source_requirement_ids: List[str] = Field(default_factory=list)


class GapEvidenceNeed(BaseModel):
    key: str = Field(min_length=1)
    evidence_type: GapEvidenceType
    value_kind: EvidenceValueKind = "text"
    proof_kind: Optional[LanguageProofKind] = None
    label: str = ""
    already_known: bool = False
    required_fields: List[str] = Field(default_factory=list)
    evidence_group: Optional[str] = None
    group_relation: Literal["all", "any"] = "all"
    minimum: Optional[float] = None
    component_minimum: Optional[float] = None
    required_quantity: Optional[float] = None
    unit: Optional[str] = None
    material_type: Optional[StandardMaterialType] = None
    item_id: Optional[str] = None
    other_value_kind: Optional[OtherCollectionKind] = None
    other_options: List[str] = Field(default_factory=list)

    @field_validator("evidence_type", mode="before")
    @classmethod
    def normalize_evidence_type(cls, value: Any) -> Any:
        if value == "material_boolean":
            return "material_status"
        if value not in get_args(GapEvidenceType):
            logger.warning(
                "unknown_gap_evidence_type value=%r fallback=generic",
                value,
            )
            return "generic"
        return value


class GapConstraintOption(BaseModel):
    key: str = ""
    kind: Optional[GapConstraintKind] = None
    minimum: Optional[float] = None
    scale: Optional[float] = None
    component_minimum: Optional[float] = None
    required_quantity: Optional[float] = None
    unit: str = ""
    component: Optional[GREScoreComponent] = None


class GapDeterministicConstraint(BaseModel):
    kind: GapConstraintKind = "none"
    relation: Literal["all", "any"] = "all"
    options: List[GapConstraintOption] = Field(default_factory=list)


class GapCourseRequirement(BaseModel):
    item_id: str = ""
    evidence_key: str = Field(min_length=1)
    course_name: str = Field(min_length=1)
    group_label: Optional[str] = None
    prerequisite_kind: Optional[Literal["concrete_course", "course_category"]] = None
    canonical_label: Optional[str] = None
    minimum_credits: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    authoritative: bool = False
    group_id: Optional[str] = None
    group_relation: Optional[Literal["all_of", "one_of"]] = None

    @field_validator("evidence_key", "course_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "group_label", "canonical_label", "unit", "group_id", mode="before"
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        return value.strip() if isinstance(value, str) and value.strip() else None


class AuthoritativePrerequisiteItem(BaseModel):
    item_id: str = Field(min_length=1)
    prerequisite_kind: Literal["concrete_course", "course_category"]
    canonical_label: Optional[str] = None
    category_label: Optional[str] = None
    display_label: str = Field(min_length=1)
    course_code: Optional[str] = None
    minimum_courses: Optional[int] = Field(default=None, ge=1)
    evidence_key: str = Field(min_length=1)


class AuthoritativePrerequisiteGroup(BaseModel):
    group_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    relation: Literal["all_of", "one_of"]
    items: List[AuthoritativePrerequisiteItem] = Field(min_length=1)


class AuthoritativeCourseCreditItem(BaseModel):
    item_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    required_quantity: float = Field(ge=0)
    unit: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)


ConditionalPredicateOperator = Literal["equals", "in"]


class GapConditionalPredicate(BaseModel):
    evidence_key: str = Field(min_length=1)
    operator: ConditionalPredicateOperator
    expected_values: List[str] = Field(min_length=1)

    @field_validator("evidence_key", mode="before")
    @classmethod
    def normalize_predicate_key(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("expected_values", mode="before")
    @classmethod
    def normalize_expected_values(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        )

    @model_validator(mode="after")
    def validate_equals_arity(self) -> "GapConditionalPredicate":
        if self.operator == "equals" and len(self.expected_values) != 1:
            raise ValueError("equals predicate requires exactly one expected value")
        return self


class GapConditionalMetadata(BaseModel):
    is_conditional: bool = False
    condition_text: Optional[str] = None
    controlling_evidence_keys: List[str] = Field(default_factory=list)
    predicate_relation: Literal["all", "any"] = "all"
    predicates: List[GapConditionalPredicate] = Field(default_factory=list)

    @field_validator("condition_text", mode="before")
    @classmethod
    def normalize_condition_text(cls, value: Any) -> Any:
        if value is None:
            return None
        return value.strip() if isinstance(value, str) and value.strip() else None

    @field_validator("controlling_evidence_keys", mode="before")
    @classmethod
    def normalize_controlling_keys(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @field_validator("predicates", mode="before")
    @classmethod
    def keep_valid_predicates(cls, value: Any) -> List[GapConditionalPredicate]:
        if not isinstance(value, list):
            logger.warning("invalid_conditional_predicates_container dropped=true")
            return []
        valid = []
        for item in value:
            try:
                valid.append(GapConditionalPredicate.model_validate(item))
            except ValidationError as error:
                logger.warning(
                    "invalid_conditional_predicate dropped=true error_type=%s",
                    type(error).__name__,
                )
        return valid


class GapOtherEvidenceDescriptor(BaseModel):
    source_evidence_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: OtherCollectionKind
    options: List[str] = Field(default_factory=list)

    @field_validator("source_evidence_key", "label", mode="before")
    @classmethod
    def normalize_other_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("options", mode="before")
    @classmethod
    def normalize_other_options(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
        )


class GapOtherItem(GapOtherEvidenceDescriptor):
    item_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)


class GapPlannerRequirementDraft(BaseModel):
    requirement_id: str
    matchable: bool
    informational_reason: str = ""
    match_strategy: GapMatchStrategy = "semantic"
    evidence_needs: List[GapEvidenceNeed] = Field(default_factory=list)
    constraint: GapDeterministicConstraint = Field(
        default_factory=GapDeterministicConstraint
    )
    course_requirements: List[GapCourseRequirement] = Field(default_factory=list)
    conditional: GapConditionalMetadata = Field(default_factory=GapConditionalMetadata)
    other_items: List[GapOtherEvidenceDescriptor] = Field(default_factory=list)


class GapPlannerEvidenceNeedDraft(BaseModel):
    key: str = Field(min_length=1)
    evidence_type: GapEvidenceType
    value_kind: EvidenceValueKind
    proof_kind: Optional[LanguageProofKind] = None
    label: str = ""

    @model_validator(mode="before")
    @classmethod
    def fill_legacy_value_kind(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("value_kind") is not None:
            return value
        normalized = dict(value)
        canonical = canonical_evidence_value_kind(
            str(normalized.get("key", "")),
            normalized.get("evidence_type"),
        )
        normalized["value_kind"] = canonical or "text"
        logger.warning(
            "gap_evidence_value_kind_missing key=%r fallback=%s",
            normalized.get("key"),
            normalized["value_kind"],
        )
        return normalized

    @field_validator("evidence_type", mode="before")
    @classmethod
    def normalize_evidence_type(cls, value: Any) -> Any:
        if value == "material_boolean":
            return "material_status"
        if value not in get_args(GapEvidenceType):
            logger.warning(
                "unknown_gap_evidence_type value=%r fallback=generic",
                value,
            )
            return "generic"
        return value


class GapPlannerRequirementLLMDraft(BaseModel):
    requirement_id: str
    matchable: bool
    informational_reason: str = ""
    match_strategy: GapMatchStrategy = "semantic"
    evidence_needs: List[GapPlannerEvidenceNeedDraft] = Field(default_factory=list)
    constraint: GapDeterministicConstraint = Field(
        default_factory=GapDeterministicConstraint
    )
    course_requirements: List[GapCourseRequirement] = Field(default_factory=list)
    conditional: GapConditionalMetadata = Field(default_factory=GapConditionalMetadata)
    other_items: List[GapOtherEvidenceDescriptor] = Field(default_factory=list)

    @field_validator("course_requirements", mode="before")
    @classmethod
    def keep_valid_course_requirements(cls, value: Any) -> Any:
        if not isinstance(value, list):
            logger.warning("invalid_course_requirements_container dropped")
            return []
        valid = []
        for item in value:
            try:
                valid.append(GapCourseRequirement.model_validate(item))
            except ValidationError as error:
                logger.warning(
                    "invalid_course_requirement_item dropped error_type=%s",
                    type(error).__name__,
                )
        return valid

    @field_validator("other_items", mode="before")
    @classmethod
    def keep_valid_other_items(cls, value: Any) -> Any:
        if not isinstance(value, list):
            logger.warning("invalid_other_items_container dropped")
            return []
        valid = []
        for item in value:
            try:
                valid.append(GapOtherEvidenceDescriptor.model_validate(item))
            except ValidationError as error:
                logger.warning(
                    "invalid_other_descriptor dropped error_type=%s",
                    type(error).__name__,
                )
        return valid


GapQuestionControlType = Literal[
    "boolean",
    "boolean_group",
    "experience_form",
    "single_select",
    "multi_select",
    "number",
    "number_group",
    "date",
    "short_text",
    "text_fallback",
]
QuestionGenerationFailureStage = Literal[
    "initial_generation_failed",
    "initial_schema_missing",
    "initial_schema_invalid",
    "repair_generation_failed",
    "repair_schema_missing",
    "repair_schema_invalid",
    "ownership_failed",
    "normalization_failed",
]
GapQuestionValuePath = Literal[
    "description",
    "status",
    "completed",
    "score",
    "scale",
    "quantity",
    "duration",
    "listening",
    "reading",
    "writing",
    "speaking",
    "date",
    "verbal",
    "quantitative",
    "analytical_writing",
    "has_experience",
    "experience_types",
    "unit",
]


class GapQuestionOption(BaseModel):
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)
    evidence_key: Optional[str] = None
    evidence_value: Any = None


class GapQuestionField(BaseModel):
    field_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    value_path: GapQuestionValuePath = "description"
    required: bool = True
    placeholder: Optional[str] = None


class GapQuestionValidation(BaseModel):
    required: bool = True
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    min_selections: Optional[int] = Field(default=None, ge=0)
    max_selections: Optional[int] = Field(default=None, ge=1)


class GapQuestionGenerationDiagnostics(BaseModel):
    requirement_id: Optional[str] = None
    allowed_evidence_keys: List[str] = Field(default_factory=list)
    group_relation: Literal["all", "any"] = "all"
    initial_schema: Optional[Dict[str, Any]] = None
    initial_failure_stage: Optional[QuestionGenerationFailureStage] = None
    initial_validator_error: Optional[str] = None
    repair_schema: Optional[Dict[str, Any]] = None
    repair_failure_stage: Optional[QuestionGenerationFailureStage] = None
    repair_validator_error: Optional[str] = None
    final_failure_stage: Optional[QuestionGenerationFailureStage] = None


class GapConditionalControllerBinding(BaseModel):
    evidence_key: str = Field(min_length=1)
    operator: ConditionalPredicateOperator
    expected_values: List[str] = Field(min_length=1)


class GapPlannerQuestion(BaseModel):
    question_id: str = ""
    requirement_id: Optional[str] = None
    question: str = ""
    prompt: str = ""
    evidence_keys: List[str] = Field(default_factory=list)
    expected_evidence_keys: List[str] = Field(default_factory=list)
    allowed_evidence_keys: List[str] = Field(default_factory=list)
    evidence_group: Optional[str] = None
    group_relation: Literal["all", "any"] = "all"
    control_type: str = "boolean"
    options: List[GapQuestionOption] = Field(default_factory=list)
    fields: List[GapQuestionField] = Field(default_factory=list)
    validation: GapQuestionValidation = Field(default_factory=GapQuestionValidation)
    allow_unknown: bool = True
    allow_negative: bool = True
    allow_other: bool = True
    schema_status: Literal["valid", "invalid", "fallback", "generation_error"] = "valid"
    schema_error_code: Optional[str] = None
    repair_attempts: int = Field(default=0, ge=0, le=1)
    generation_diagnostics: Optional[GapQuestionGenerationDiagnostics] = None
    conditional_controller_bindings: List[GapConditionalControllerBinding] = Field(
        default_factory=list
    )

    @field_validator("question", "prompt", mode="before")
    @classmethod
    def normalize_prompt_text(cls, value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @field_validator(
        "evidence_keys",
        "expected_evidence_keys",
        "allowed_evidence_keys",
        mode="before",
    )
    @classmethod
    def normalize_question_keys(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    @field_validator("group_relation", mode="before")
    @classmethod
    def normalize_group_relation(cls, value: Any) -> str:
        return value if value in {"all", "any"} else "all"

    @field_validator("control_type", mode="before")
    @classmethod
    def normalize_control_type(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ""

    @field_validator("options", mode="before")
    @classmethod
    def keep_valid_options(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        valid = []
        for option in value:
            try:
                valid.append(GapQuestionOption.model_validate(option))
            except ValidationError:
                logger.warning("invalid_gap_question_option dropped")
        return valid

    @field_validator("fields", mode="before")
    @classmethod
    def keep_valid_fields(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        valid = []
        for field in value:
            try:
                valid.append(GapQuestionField.model_validate(field))
            except ValidationError:
                logger.warning("invalid_gap_question_field dropped")
        return valid

    @field_validator("validation", mode="before")
    @classmethod
    def normalize_validation(cls, value: Any) -> Any:
        try:
            return GapQuestionValidation.model_validate(value or {})
        except ValidationError:
            logger.warning("invalid_gap_question_validation fallback=default")
            return GapQuestionValidation()

    @model_validator(mode="after")
    def synchronize_legacy_fields(self) -> "GapPlannerQuestion":
        prompt = (self.prompt or self.question).strip()
        keys = self.expected_evidence_keys or self.evidence_keys
        self.prompt = prompt
        self.question = prompt
        self.expected_evidence_keys = list(dict.fromkeys(keys))
        self.evidence_keys = list(self.expected_evidence_keys)
        return self


class GapPlannerQuestionLLMDraft(BaseModel):
    question_id: str = ""
    requirement_id: Optional[str] = None
    prompt: str = ""
    expected_evidence_keys: List[str] = Field(default_factory=list)
    group_relation: Literal["all", "any"] = "all"
    control_type: str = ""
    options: List[GapQuestionOption] = Field(default_factory=list)
    fields: List[GapQuestionField] = Field(default_factory=list)
    validation: GapQuestionValidation = Field(default_factory=GapQuestionValidation)
    allow_unknown: bool = True
    allow_negative: bool = True
    allow_other: bool = True

    @field_validator("control_type", mode="before")
    @classmethod
    def normalize_control_type(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ""

    @field_validator("options", mode="before")
    @classmethod
    def keep_valid_options(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        valid = []
        for option in value:
            try:
                valid.append(GapQuestionOption.model_validate(option))
            except ValidationError:
                logger.warning("invalid_gap_question_option dropped")
        return valid

    @field_validator("fields", mode="before")
    @classmethod
    def keep_valid_fields(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        valid = []
        for field in value:
            try:
                valid.append(GapQuestionField.model_validate(field))
            except ValidationError:
                logger.warning("invalid_gap_question_field dropped")
        return valid

    @field_validator("validation", mode="before")
    @classmethod
    def normalize_validation(cls, value: Any) -> Any:
        try:
            return GapQuestionValidation.model_validate(value or {})
        except ValidationError:
            logger.warning("invalid_gap_question_validation fallback=default")
            return GapQuestionValidation()

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_question_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if not normalized.get("prompt") and normalized.get("question"):
            normalized["prompt"] = normalized["question"]
        if (
            not normalized.get("expected_evidence_keys")
            and normalized.get("evidence_keys")
        ):
            normalized["expected_evidence_keys"] = normalized["evidence_keys"]
        return normalized


class GapPlannerLLMOutput(BaseModel):
    requirements: List[GapPlannerRequirementLLMDraft] = Field(default_factory=list)
    questions: List[GapPlannerQuestionLLMDraft] = Field(default_factory=list)


class GapQuestionRepairOutput(BaseModel):
    questions: List[GapPlannerQuestionLLMDraft] = Field(default_factory=list)


class GapPlannerOutput(BaseModel):
    requirements: List[GapPlannerRequirementDraft] = Field(default_factory=list)
    questions: List[GapPlannerQuestion] = Field(default_factory=list)


class GapPlannedRequirement(GapPlannerRequirementDraft):
    other_items: List[GapOtherItem] = Field(default_factory=list)
    category: RequirementCategory
    requirement: str
    requirement_zh: Optional[str] = None
    importance: RequirementImportance
    requirement_verification_status: Literal[
        "official_verified", "model_memory_unverified", "user_supplied"
    ]
    source_url: Optional[str] = None
    source_cycle: Optional[str] = None
    temporal_applicability: RequirementTemporalApplicability
    temporal_note: Optional[str] = None
    user_matchable: bool = True
    conditional_state: ConditionalApplicabilityState = "not_conditional"
    parent_requirement_id: Optional[str] = None
    parent_requirement_text: Optional[str] = None
    parent_has_explicit_conditional_scope: bool = False
    conditional_scope_source: Literal["none", "self", "parent"] = "none"
    route_scope: ApplicationRouteScope = "standard"
    excluded_reason: Optional[RequirementExclusionReason] = None
    route_scope_source: Literal["current_requirement", "named_route", "parent"] = (
        "current_requirement"
    )


class GapPlan(BaseModel):
    target_program: TargetProgram
    requirements: List[GapPlannedRequirement] = Field(default_factory=list)
    questions: List[GapPlannerQuestion] = Field(default_factory=list)
    reusable_evidence: List[UserEvidence] = Field(default_factory=list)
    planning_llm_requests: int = 1


class GapPlanRequest(BaseModel):
    target_program: TargetProgram
    requirements_review: TargetProgramRequirementsReview
    user_profile: UserProfile = Field(default_factory=UserProfile)
    user_evidence: List[UserEvidence] = Field(default_factory=list)
    authoritative_prerequisite_plan: List[AuthoritativePrerequisiteGroup] = Field(
        default_factory=list
    )
    authoritative_course_credit_plan: List[AuthoritativeCourseCreditItem] = Field(
        default_factory=list
    )


SpecialPrerequisiteRelation = Literal["all_of", "one_of"]
SpecialExpectedAnswerType = Literal["ternary"]


class SpecialPrerequisiteCourseExtraction(BaseModel):
    prerequisite_kind: Literal["concrete_course", "course_category"]
    canonical_label: Optional[str] = None
    category_label: Optional[str] = None
    minimum_courses: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "SpecialPrerequisiteCourseExtraction":
        if self.prerequisite_kind == "concrete_course":
            if not self.canonical_label or not self.canonical_label.strip():
                raise ValueError("concrete_course requires canonical_label")
            self.canonical_label = self.canonical_label.strip()
            self.category_label = None
            self.minimum_courses = None
        else:
            if not self.category_label or not self.category_label.strip():
                raise ValueError("course_category requires category_label")
            self.category_label = self.category_label.strip()
            self.canonical_label = None
        return self


class SpecialPrerequisiteGroupExtraction(BaseModel):
    requirement_id: str = Field(min_length=1)
    relation: SpecialPrerequisiteRelation
    courses: List[SpecialPrerequisiteCourseExtraction] = Field(min_length=1)


class SpecialObjectiveRequirementExtraction(BaseModel):
    requirement_id: str = Field(min_length=1)
    canonical_label: str = Field(min_length=1)
    special_type: str = Field(min_length=1)
    expected_answer_type: SpecialExpectedAnswerType = "ternary"


class SpecialAggregateCourseCreditExtraction(BaseModel):
    requirement_id: str = Field(min_length=1)
    required_quantity: float = Field(ge=0)
    unit: str = Field(min_length=1)
    label: str = Field(min_length=1)

    @field_validator("requirement_id", "unit", "label", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class SpecialTargetedExtractionOutput(BaseModel):
    prerequisite_groups: List[SpecialPrerequisiteGroupExtraction] = Field(
        default_factory=list
    )
    objective_special_requirements: List[SpecialObjectiveRequirementExtraction] = Field(
        default_factory=list
    )
    aggregate_course_credits: List[SpecialAggregateCourseCreditExtraction] = Field(
        default_factory=list
    )


class SpecialInterviewCourseItem(BaseModel):
    item_id: str = Field(min_length=1)
    prerequisite_kind: Literal["concrete_course", "course_category"]
    canonical_label: Optional[str] = None
    category_label: Optional[str] = None
    minimum_courses: Optional[int] = None
    evidence_key: str
    suggested_user_courses: List[str] = Field(default_factory=list)


class SpecialInterviewSource(BaseModel):
    requirement_id: str
    requirement: str
    requirement_zh: Optional[str] = None
    source_url: Optional[str] = None
    verification_status: Literal["official_verified", "user_supplied"]


class SpecialInterviewPrerequisiteGroup(BaseModel):
    group_id: str
    relation: SpecialPrerequisiteRelation
    courses: List[SpecialInterviewCourseItem]
    source: SpecialInterviewSource


class SpecialInterviewObjectiveItem(BaseModel):
    item_id: str
    canonical_label: str
    evidence_key: str
    special_type: str
    expected_answer_type: SpecialExpectedAnswerType = "ternary"
    source: SpecialInterviewSource


class SpecialInterviewAggregateCreditItem(AuthoritativeCourseCreditItem):
    source: SpecialInterviewSource


class SpecialInterviewPlanRequest(BaseModel):
    target_program: TargetProgram
    requirements_review: TargetProgramRequirementsReview
    user_evidence: List[UserEvidence] = Field(default_factory=list)


class SpecialInterviewPlan(BaseModel):
    target_program: TargetProgram
    prerequisite_groups: List[SpecialInterviewPrerequisiteGroup] = Field(
        default_factory=list
    )
    authoritative_prerequisite_plan: List[AuthoritativePrerequisiteGroup] = Field(
        default_factory=list
    )
    aggregate_course_credits: List[SpecialInterviewAggregateCreditItem] = Field(
        default_factory=list
    )
    authoritative_course_credit_plan: List[AuthoritativeCourseCreditItem] = Field(
        default_factory=list
    )
    objective_special_requirements: List[SpecialInterviewObjectiveItem] = Field(
        default_factory=list
    )
    reusable_evidence: List[UserEvidence] = Field(default_factory=list)
    trusted_requirement_count: int = 0
    extracted_item_count: int = 0
    remaining_item_count: int = 0
    extraction_llm_requests: int = 0


class SpecialInterviewAnswer(BaseModel):
    evidence_key: str = Field(min_length=1)
    item_id: Optional[str] = None
    canonical_label: str = Field(min_length=1)
    item_type: Literal[
        "prerequisite_course", "objective_special", "aggregate_course_credit"
    ]
    prerequisite_kind: Optional[Literal["concrete_course", "course_category"]] = None
    minimum_courses: Optional[int] = Field(default=None, ge=1)
    availability: EvidenceAvailability
    requirement_id: str = Field(min_length=1)
    user_course_name: Optional[str] = None
    user_course_names: List[str] = Field(default_factory=list)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    required_quantity: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_aggregate_credit_answer(self) -> "SpecialInterviewAnswer":
        if self.item_type != "aggregate_course_credit":
            return self
        if self.availability == "known_negative":
            raise ValueError("aggregate course credit does not support known_negative")
        if not self.unit or not self.unit.strip() or self.required_quantity is None:
            raise ValueError("aggregate course credit metadata is required")
        self.unit = self.unit.strip()
        if self.availability == "known" and self.quantity is None:
            raise ValueError("known aggregate course credit requires quantity")
        if self.availability == "unknown":
            self.quantity = None
        return self


class SpecialInterviewEvidenceSubmitRequest(BaseModel):
    target_program: TargetProgram
    answers: List[SpecialInterviewAnswer] = Field(min_length=1)


class SpecialInterviewEvidenceSubmitResponse(BaseModel):
    evidence: List[UserEvidence]
    parser_calls: Literal[0] = 0
    llm_requests: Literal[0] = 0


class GapQuestionRepairRequest(BaseModel):
    question: GapPlannerQuestion
    requirement: GapPlannedRequirement
    user_profile: UserProfile = Field(default_factory=UserProfile)
    user_evidence: List[UserEvidence] = Field(default_factory=list)


class GapEvidenceParseRequest(BaseModel):
    question: GapPlannerQuestion
    evidence_needs: List[GapEvidenceNeed]
    answer: str = Field(min_length=1)
    existing_evidence: List[UserEvidence] = Field(default_factory=list)


class GapEvidenceParseResponse(BaseModel):
    evidence: List[UserEvidence]
    missing_slots: List[str] = Field(default_factory=list)
    follow_up_question: Optional[str] = None
    satisfied_evidence_groups: List[str] = Field(default_factory=list)
    slot_states: Dict[str, EvidenceSlotStatus] = Field(default_factory=dict)
    parser_calls: int = 0


class GapStructuredAnswer(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    selected_options: List[str] = Field(default_factory=list)
    terminal_state: Optional[Literal["known_negative", "unknown"]] = None


class CourseRequirementEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    course_name: str = Field(min_length=1)
    completed: bool


class CourseCreditEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    quantity: float = Field(ge=0)
    unit: str = Field(min_length=1)


class GREScoreEvidenceValue(BaseModel):
    verbal: Optional[float] = Field(default=None, ge=0)
    quantitative: Optional[float] = Field(default=None, ge=0)
    analytical_writing: Optional[float] = Field(default=None, ge=0)


class ExperienceDurationValue(BaseModel):
    quantity: float = Field(ge=0)
    unit: ExperienceDurationUnit


class ExperienceEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    has_experience: bool
    experience_types: List[ExperienceType] = Field(default_factory=list)
    duration: Optional[ExperienceDurationValue] = None

    @model_validator(mode="after")
    def validate_experience_state(self) -> "ExperienceEvidenceValue":
        if not self.has_experience:
            self.experience_types = []
            self.duration = None
            return self
        if not self.experience_types or self.duration is None:
            raise ValueError("experience types and duration are required when experience exists")
        return self


class MaterialItemEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    material_type: StandardMaterialType
    label: str = Field(min_length=1)
    available: bool


class MaterialQuantityEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    material_type: Literal["recommendation_letters"]
    quantity: float = Field(ge=0)


class OtherItemEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: OtherCollectionKind
    value: Any
    options: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_typed_other_value(self) -> "OtherItemEvidenceValue":
        if self.value_kind == "boolean" and not isinstance(self.value, bool):
            raise ValueError("boolean Other evidence must be boolean")
        if self.value_kind == "numeric" and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("numeric Other evidence must be numeric")
        if self.value_kind == "single_select" and (
            not isinstance(self.value, str) or self.value not in self.options
        ):
            raise ValueError("single-select Other evidence must use one allowed option")
        if self.value_kind == "multi_select" and (
            not isinstance(self.value, list)
            or not self.value
            or any(item not in self.options for item in self.value)
        ):
            raise ValueError("multi-select Other evidence must use allowed options")
        if self.value_kind == "short_text" and (
            not isinstance(self.value, str)
            or not self.value.strip()
            or len(self.value.strip()) > 200
        ):
            raise ValueError("short-text Other evidence must contain 1-200 characters")
        return self


class ConditionalControllerEvidenceValue(BaseModel):
    requirement_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: Literal["boolean"] = "boolean"
    matches_condition: bool
    value: Optional[str] = None

    @model_validator(mode="after")
    def validate_controller_value(self) -> "ConditionalControllerEvidenceValue":
        if self.matches_condition and not self.value:
            raise ValueError("matching controller evidence requires a predicate value")
        if not self.matches_condition:
            self.value = None
        return self


class GapStructuredEvidenceRequest(BaseModel):
    question: GapPlannerQuestion
    evidence_needs: List[GapEvidenceNeed]
    answer: GapStructuredAnswer
    existing_evidence: List[UserEvidence] = Field(default_factory=list)


class SemanticGapJudgement(BaseModel):
    requirement_id: str
    status: GapStatus
    reason: str
    user_evidence: str
    matched_quantities: List[float] = Field(default_factory=list)


class SemanticGapOutput(BaseModel):
    judgements: List[SemanticGapJudgement] = Field(default_factory=list)


class GapResult(BaseModel):
    requirement_id: str
    category: RequirementCategory
    requirement: str
    requirement_zh: Optional[str] = None
    requirement_verification_status: Literal[
        "official_verified", "model_memory_unverified", "user_supplied"
    ]
    importance: RequirementImportance = "unknown"
    status: GapStatus
    reason_code: GapReasonCode = "semantic_evidence_insufficient"
    user_evidence: str
    gap: str
    reason: str
    source_url: Optional[str] = None
    source_cycle: Optional[str] = None
    temporal_applicability: RequirementTemporalApplicability
    temporal_note: Optional[str] = None
    conditional_state: ConditionalApplicabilityState = "not_conditional"


class GapAnalysisRequest(BaseModel):
    target_program: TargetProgram
    plan: GapPlan
    user_profile: UserProfile = Field(default_factory=UserProfile)
    user_evidence: List[UserEvidence] = Field(default_factory=list)


class GapAnalysisResponse(BaseModel):
    target_program: TargetProgram
    results: List[GapResult]
    informational_requirements: List[GapPlannedRequirement] = Field(default_factory=list)
    semantic_llm_requests: int = 0


PlanningActionKind = Literal[
    "complete_gap",
    "resolve_gap",
    "confirm_information",
]
PlanningPriority = Literal["high", "medium", "optional"]
PlanningTrack = Literal["main", "optional"]
PlanningActionStatus = Literal["pending", "in_progress", "completed", "blocked"]
PlanningTimingStatus = Literal["scheduled", "urgent", "priority_only"]


class ActionPlanRequest(BaseModel):
    target_program: TargetProgram
    gap_analysis: GapAnalysisResponse
    application_timeline: ApplicationTimeline


class DeepSeekPlanningActionDraft(BaseModel):
    action_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    time_period: str = Field(min_length=1)
    target_date: Optional[str] = None
    source_gap_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: PlanningActionStatus = "pending"
    depends_on: List[str] = Field(default_factory=list)
    parallel_group: Optional[str] = None


class DeepSeekActionPlanContent(BaseModel):
    actions: List[DeepSeekPlanningActionDraft] = Field(default_factory=list)


class PlanningActionDraft(DeepSeekPlanningActionDraft):
    action_kind: PlanningActionKind


class DeepSeekActionPlanOutput(BaseModel):
    actions: List[PlanningActionDraft] = Field(default_factory=list)


class PlanningAction(PlanningActionDraft):
    priority: PlanningPriority
    requirement_type: RequirementImportance
    plan_track: PlanningTrack
    priority_order: int = Field(ge=1)
    timing_status: PlanningTimingStatus


class PlanningConfirmationItem(BaseModel):
    source_gap_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    action_kind: Literal["confirm_information"] = "confirm_information"
    target_date: None = None


class PlanningEligibilityRisk(BaseModel):
    source_gap_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    target_date: None = None


class ActionPlan(BaseModel):
    target_program: TargetProgram
    generated_at: str
    current_date: str
    timeline_status: Literal["complete", "partial", "not_found"]
    application_deadline: Optional[str] = None
    application_deadline_label: Optional[str] = None
    deadline_is_precise: bool = False
    ready_by_date: Optional[str] = None
    needs_confirmation: List[PlanningConfirmationItem] = Field(default_factory=list)
    eligibility_risks: List[PlanningEligibilityRisk] = Field(default_factory=list)
    actions: List[PlanningAction] = Field(default_factory=list)
    planning_llm_requests: int = 0


class OverallRanking(BaseModel):
    edition: int
    rank_display: str
    rank_min: int
    rank_max: Optional[int] = None


class SubjectRanking(BaseModel):
    subject: str
    edition: int
    rank_display: str
    rank_min: int
    rank_max: Optional[int] = None


OverallRankingStatus = Literal["ranked", "not_ranked", "unknown"]


class CandidateUniversity(BaseModel):
    university: str
    country: str
    ranking: int
    rank_display: str
    rank_min: int
    rank_max: Optional[int] = None
    ranking_system: Literal["QS"] = "QS"
    ranking_basis: Literal["overall", "subject"] = "overall"
    ranking_subject: Optional[str] = None
    ranking_edition: int
    ranking_source_url: str
    overall_ranking: Optional[OverallRanking] = None
    overall_ranking_status: OverallRankingStatus = "unknown"
    subject_ranking: Optional[SubjectRanking] = None
    school_official_url: Optional[str] = None


class CandidateUniversityResult(BaseModel):
    universities: List[CandidateUniversity] = Field(default_factory=list)


class UniversityProgramRequest(BaseModel):
    target: ExploreTargetRequest
    university: CandidateUniversity


app = FastAPI(
    title="AI University Application Analysis API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/", tags=["system"])
async def root() -> Dict[str, str]:
    return {"message": "API is running"}


@app.get("/health", tags=["system"])
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


def safe_error_message(error: Exception, api_key: str) -> str:
    """Return useful diagnostic text without exposing the configured API key."""
    messages = []
    current_error: Optional[BaseException] = error
    while current_error and len(messages) < 3:
        error_type = type(current_error).__name__
        error_text = str(current_error) or "no additional details"
        message = f"{error_type}: {error_text}"
        if message not in messages:
            messages.append(message)
        current_error = current_error.__cause__

    message = " -> ".join(messages) or type(error).__name__
    return message.replace(api_key, "[REDACTED]") if api_key else message


class DeepSeekTextResult(BaseModel):
    content: str
    stop_reason: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


async def call_deepseek(
    messages: List[Dict[str, str]],
    max_tokens: int,
    response_format: Optional[Dict[str, str]] = None,
    *,
    include_metadata: bool = False,
    diagnostic_label: Optional[str] = None,
) -> Any:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY is not configured in backend/.env",
        )

    request_options: Dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if response_format:
        request_options["response_format"] = response_format

    try:
        async with httpx.AsyncClient(trust_env=False) as http_client:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=DEEPSEEK_BASE_URL,
                http_client=http_client,
            )
            response = await client.chat.completions.create(**request_options)
    except APIConnectionError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to connect to DeepSeek API: {safe_error_message(error, api_key)}",
        ) from error
    except APIStatusError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                f"DeepSeek API returned HTTP {error.status_code}: "
                f"{safe_error_message(error, api_key)}"
            ),
        ) from error
    except OpenAIError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek API request failed: {safe_error_message(error, api_key)}",
        ) from error

    choice = response.choices[0]
    content = choice.message.content
    usage = response.usage
    result = DeepSeekTextResult(
        content=content or "",
        stop_reason=getattr(choice, "finish_reason", None),
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=getattr(usage, "total_tokens", None) if usage else None,
    )
    if diagnostic_label:
        logger.info(
            "%s stop_reason=%s input_tokens=%s output_tokens=%s total_tokens=%s final_text_length=%d",
            diagnostic_label,
            result.stop_reason,
            result.input_tokens,
            result.output_tokens,
            result.total_tokens,
            len(result.content),
        )
    if not content and not include_metadata:
        raise HTTPException(status_code=502, detail="DeepSeek API returned an empty response")
    return result if include_metadata else result.content


@app.get("/deepseek-test", tags=["system"])
async def deepseek_test() -> Dict[str, str]:
    content = await call_deepseek(
        messages=[{"role": "user", "content": "只回复：连接成功"}],
        max_tokens=16,
    )
    return {"model": DEEPSEEK_MODEL, "reply": content}


def load_qs_subject_taxonomy() -> Dict[str, Any]:
    if not QS_SUBJECTS_FILE.exists():
        raise HTTPException(status_code=503, detail="QS Subject taxonomy file is missing")
    try:
        data = json.loads(QS_SUBJECTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=503, detail=f"Unable to read QS Subject taxonomy: {error}") from error
    subjects = data.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise HTTPException(status_code=503, detail="QS Subject taxonomy is empty")
    return data


def qs_subject_records() -> Dict[str, Dict[str, Any]]:
    taxonomy = load_qs_subject_taxonomy()
    return {
        item["subject"]: item
        for item in taxonomy["subjects"]
        if isinstance(item, dict) and isinstance(item.get("subject"), str)
    }


def qs_subject_id(subject_name: str) -> str:
    normalized = subject_name.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def qs_subject_records_by_id() -> Dict[str, Dict[str, Any]]:
    return {
        qs_subject_id(subject_name): record
        for subject_name, record in qs_subject_records().items()
    }


@app.get("/rankings/qs/subjects", tags=["rankings"])
async def list_qs_subjects() -> Dict[str, Any]:
    """Return the locally imported, official QS Subject taxonomy."""
    taxonomy = load_qs_subject_taxonomy()
    return {
        **taxonomy,
        "subjects": [
            {
                **item,
                "subject_id": qs_subject_id(item["subject"]),
                "subject_name": item["subject"],
            }
            for item in taxonomy["subjects"]
            if isinstance(item, dict) and isinstance(item.get("subject"), str)
        ],
    }


QS_COUNTRY_FILTERS: Dict[str, List[str]] = {
    "美国": ["United States of America"],
    "英国": ["United Kingdom"],
    "中国香港": ["Hong Kong SAR, China", "Hong Kong SAR"],
    "新加坡": ["Singapore"],
    "澳大利亚": ["Australia"],
    "加拿大": ["Canada"],
    "德国": ["Germany"],
    "欧洲其他地区": [
        "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
        "Denmark", "Estonia", "Finland", "France", "Greece",
        "Hungary", "Iceland", "Ireland", "Italy", "Latvia", "Lithuania",
        "Luxembourg", "Malta", "Netherlands", "Norway", "Poland", "Portugal",
        "Romania", "Serbia", "Slovakia", "Slovenia", "Spain", "Sweden",
        "Switzerland",
    ],
}

EUROPE_COUNTRY_LABELS: Dict[str, str] = {
    "Austria": "奥地利",
    "Belgium": "比利时",
    "Bulgaria": "保加利亚",
    "Croatia": "克罗地亚",
    "Cyprus": "塞浦路斯",
    "Czechia": "捷克",
    "Denmark": "丹麦",
    "Estonia": "爱沙尼亚",
    "Finland": "芬兰",
    "France": "法国",
    "Greece": "希腊",
    "Hungary": "匈牙利",
    "Iceland": "冰岛",
    "Ireland": "爱尔兰",
    "Italy": "意大利",
    "Latvia": "拉脱维亚",
    "Lithuania": "立陶宛",
    "Luxembourg": "卢森堡",
    "Malta": "马耳他",
    "Netherlands": "荷兰",
    "Norway": "挪威",
    "Poland": "波兰",
    "Portugal": "葡萄牙",
    "Romania": "罗马尼亚",
    "Serbia": "塞尔维亚",
    "Slovakia": "斯洛伐克",
    "Slovenia": "斯洛文尼亚",
    "Spain": "西班牙",
    "Sweden": "瑞典",
    "Switzerland": "瑞士",
}

QS_COUNTRY_DISPLAY_LABELS: Dict[str, str] = {
    **EUROPE_COUNTRY_LABELS,
    "Argentina": "阿根廷",
    "Australia": "澳大利亚",
    "Canada": "加拿大",
    "China (Mainland)": "中国大陆",
    "Germany": "德国",
    "Hong Kong SAR": "中国香港",
    "Hong Kong SAR, China": "中国香港",
    "Japan": "日本",
    "Malaysia": "马来西亚",
    "New Zealand": "新西兰",
    "Republic of Korea": "韩国",
    "Saudi Arabia": "沙特阿拉伯",
    "Singapore": "新加坡",
    "Taiwan": "中国台湾",
    "United Kingdom": "英国",
    "United States of America": "美国",
}


def requested_qs_countries(countries: List[str]) -> tuple[List[str], Dict[str, str]]:
    database_countries: List[str] = []
    display_names: Dict[str, str] = {}
    for country in countries:
        mapped = QS_COUNTRY_FILTERS.get(country, [country])
        for database_country in mapped:
            if database_country not in database_countries:
                database_countries.append(database_country)
                if country == "欧洲其他地区":
                    local_country = EUROPE_COUNTRY_LABELS.get(
                        database_country,
                        database_country,
                    )
                    display_names[database_country] = f"欧洲其他地区 · {local_country}"
                else:
                    display_names[database_country] = country
    return database_countries, display_names


def normalized_university_name(university: str) -> str:
    return re.sub(r"[\W_]+", "", university.casefold().replace("&", "and"))


def has_possible_overall_name_match(
    university: str,
    country_region: str,
    overall_identities: Dict[str, List[str]],
) -> bool:
    normalized_subject_name = normalized_university_name(university)
    for normalized_overall_name in overall_identities.get(country_region, []):
        if normalized_subject_name == normalized_overall_name:
            return True
        if SequenceMatcher(
            None,
            normalized_subject_name,
            normalized_overall_name,
        ).ratio() >= 0.9:
            return True
    return False


async def _filter_candidate_universities(
    target: ExploreTargetRequest,
) -> CandidateUniversityResult:
    """Filter the locally imported QS rankings without enriching external metadata."""
    if target.ranking.min > target.ranking.max:
        raise HTTPException(
            status_code=422,
            detail="ranking.min must be less than or equal to ranking.max",
        )
    if not QS_RANKINGS_DB.exists():
        raise HTTPException(status_code=503, detail="Local QS rankings database is missing")

    ranking_subject: Optional[str] = None
    if target.ranking.basis == "overall":
        edition = 2027
    else:
        subject_id = (target.ranking_subject_id or "").strip()
        supplied_name = (target.ranking_subject or "").strip()
        if subject_id:
            subject_record = qs_subject_records_by_id().get(subject_id)
            ranking_subject = (
                str(subject_record["subject"]) if subject_record is not None else None
            )
            if subject_record is not None and supplied_name and supplied_name != ranking_subject:
                raise HTTPException(
                    status_code=422,
                    detail="ranking_subject_id and ranking_subject do not identify the same QS Subject",
                )
        else:
            ranking_subject = supplied_name
            subject_record = qs_subject_records().get(ranking_subject)
        if subject_record is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "ranking_subject_id or ranking_subject must identify an exact Subject "
                    "from the local QS taxonomy"
                ),
            )
        edition = int(subject_record["edition"])

    database_countries, display_names = requested_qs_countries(target.countries)
    query = (
        "SELECT r.university, r.country_region, r.rank_display, r.rank_min, r.rank_max, "
        "o.rank_display AS overall_rank_display, o.rank_min AS overall_rank_min, "
        "o.rank_max AS overall_rank_max "
        "FROM rankings r LEFT JOIN rankings o "
        "ON ? = 'subject' AND o.ranking_system = 'QS' AND o.scope = 'overall' "
        "AND o.edition = 2027 AND o.university = r.university "
        "AND o.country_region = r.country_region "
        "WHERE r.ranking_system = 'QS' AND r.scope = ? AND r.edition = ? "
    )
    parameters: List[Any] = [target.ranking.basis, target.ranking.basis, edition]
    if ranking_subject is not None:
        query += "AND r.subject = ? "
        parameters.append(ranking_subject)
    if database_countries:
        placeholders = ", ".join("?" for _ in database_countries)
        query += f"AND r.country_region IN ({placeholders}) "
        parameters.extend(database_countries)
    query += (
        "AND r.rank_min <= ? AND COALESCE(r.rank_max, r.rank_min) >= ? "
        "ORDER BY r.rank_min ASC, COALESCE(r.rank_max, r.rank_min) ASC, r.university ASC"
    )
    parameters.extend([target.ranking.max, target.ranking.min])

    overall_identities: Dict[str, List[str]] = {}
    try:
        with sqlite3.connect(f"file:{QS_RANKINGS_DB}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
            if target.ranking.basis == "subject":
                for identity_row in connection.execute(
                    "SELECT university, country_region FROM rankings "
                    "WHERE ranking_system = 'QS' AND scope = 'overall' AND edition = 2027"
                ).fetchall():
                    overall_identities.setdefault(
                        identity_row["country_region"],
                        [],
                    ).append(normalized_university_name(identity_row["university"]))
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail=f"Unable to query local QS rankings: {error}") from error

    universities: List[CandidateUniversity] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["university"], row["country_region"])
        if key in seen:
            continue
        seen.add(key)
        current_ranking = {
            "edition": edition,
            "rank_display": row["rank_display"],
            "rank_min": int(row["rank_min"]),
            "rank_max": int(row["rank_max"]) if row["rank_max"] is not None else None,
        }
        overall_ranking: Optional[OverallRanking]
        subject_ranking: Optional[SubjectRanking]
        if target.ranking.basis == "subject":
            overall_ranking = (
                OverallRanking(
                    edition=2027,
                    rank_display=row["overall_rank_display"],
                    rank_min=int(row["overall_rank_min"]),
                    rank_max=(
                        int(row["overall_rank_max"])
                        if row["overall_rank_max"] is not None
                        else None
                    ),
                )
                if row["overall_rank_display"] is not None
                else None
            )
            subject_ranking = SubjectRanking(
                subject=ranking_subject or "",
                **current_ranking,
            )
            if overall_ranking is not None:
                overall_ranking_status: OverallRankingStatus = "ranked"
            elif has_possible_overall_name_match(
                row["university"],
                row["country_region"],
                overall_identities,
            ):
                overall_ranking_status = "unknown"
            else:
                overall_ranking_status = "not_ranked"
        else:
            overall_ranking = OverallRanking(**current_ranking)
            overall_ranking_status = "ranked"
            subject_ranking = None
        universities.append(
            CandidateUniversity(
                university=row["university"],
                country=display_names.get(
                    row["country_region"],
                    QS_COUNTRY_DISPLAY_LABELS.get(
                        row["country_region"],
                        row["country_region"],
                    ),
                ),
                ranking=int(row["rank_min"]),
                rank_display=row["rank_display"],
                rank_min=int(row["rank_min"]),
                rank_max=int(row["rank_max"]) if row["rank_max"] is not None else None,
                ranking_system="QS",
                ranking_basis=target.ranking.basis,
                ranking_subject=ranking_subject,
                ranking_edition=edition,
                ranking_source_url="",
                overall_ranking=overall_ranking,
                overall_ranking_status=overall_ranking_status,
                subject_ranking=subject_ranking,
            )
        )
    return CandidateUniversityResult(universities=universities)


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class DeepSeekWebSearchNoFinalTextError(HTTPException):
    """HTTP 200 response had parseable JSON but no usable final text block."""

    def __init__(self, schema_name: str) -> None:
        super().__init__(
            status_code=502,
            detail=f"DeepSeek Web Search returned malformed {schema_name} data",
        )


def parse_json_object(text: str) -> Dict[str, Any]:
    """Extract one JSON object from otherwise well-formed model wrapper text."""
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("response did not contain a JSON object")


async def call_deepseek_web_search(
    prompt: str,
    output_model: Type[StructuredOutputT],
    *,
    schema_name: str,
    max_output_tokens: int,
    max_search_uses: int = 6,
) -> StructuredOutputT:
    """Run one server-side Web Search request and parse only its JSON schema output."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY is not configured in backend/.env",
        )

    schema_prompt = (
        f"{prompt}\n\nReturn only one JSON object matching this JSON Schema exactly:\n"
        f"{json.dumps(output_model.model_json_schema(), ensure_ascii=False)}"
    )
    request_body = {
        "model": DEEPSEEK_MODEL,
        "max_tokens": max_output_tokens,
        "messages": [{"role": "user", "content": schema_prompt}],
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_search_uses,
            }
        ],
    }
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/anthropic/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail="DeepSeek Web Search timed out. Please retry.",
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to connect to DeepSeek Web Search: "
                f"{safe_error_message(error, api_key)}"
            ),
        ) from error

    if response.is_error:
        detail = response.text[:1200].replace(api_key, "[REDACTED]")
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek Web Search returned HTTP {response.status_code}: {detail}",
        )
    text = ""
    try:
        payload = response.json()
        output = payload.get("content", [])
        content_block_types = [
            str(item.get("type") or "unknown")
            for item in output
            if isinstance(item, dict)
        ]
        tool_block_count = sum(
            "tool" in block_type.casefold() for block_type in content_block_types
        )
        web_search_block_count = sum(
            (
                "web_search" in str(item.get("type") or "").casefold()
                or str(item.get("name") or "").casefold() == "web_search"
            )
            for item in output
            if isinstance(item, dict)
        )
        text = "\n".join(
            str(item.get("text") or "")
            for item in output
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        logger.info(
            "deepseek_web_search_response schema=%s stop_reason=%s usage=%s "
            "content_block_types=%s tool_block_count=%d web_search_block_count=%d "
            "final_text_length=%d",
            schema_name,
            payload.get("stop_reason"),
            payload.get("usage"),
            content_block_types,
            tool_block_count,
            web_search_block_count,
            len(text),
        )
        if not text:
            raise DeepSeekWebSearchNoFinalTextError(schema_name)
        structured_value = parse_json_object(text)
        try:
            return output_model.model_validate(structured_value)
        except ValidationError as error:
            logger.warning(
                "deepseek_web_search_schema_error schema=%s errors=%s output=%s",
                schema_name,
                error.errors(include_url=False),
                text[:2400],
            )
            raise
    except (ValueError, ValidationError, AttributeError) as error:
        logger.warning(
            "deepseek_web_search_parse_error schema=%s error=%s output=%s",
            schema_name,
            str(error),
            text[:2400],
        )
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek Web Search returned malformed {schema_name} data",
        ) from error


async def enrich_school_official_urls(
    universities: List[CandidateUniversity],
) -> List[CandidateUniversity]:
    """Ask the search-enabled model for school URLs; URLs are references, not gates."""
    if not universities:
        return universities

    async def enrich_batch(
        offset: int,
        batch: List[CandidateUniversity],
    ) -> Dict[int, Optional[str]]:
        school_queries = [
            {
                "index": offset + index,
                "university": school.university,
                "country_or_region": school.country,
            }
            for index, school in enumerate(batch)
        ]
        prompt = (
            "Use Web Search to find the current official homepage for every listed "
            "university. Decide the correct institution and URL semantically. Prefer the "
            "institution's own canonical homepage. Return the original index and the URL "
            "you selected. Use null when you cannot confidently identify it. Do not invent "
            "a URL, and do not explain the result.\n\n"
            f"Schools: {json.dumps(school_queries, ensure_ascii=False)}"
        )
        try:
            result = await call_deepseek_web_search(
                prompt,
                SchoolOfficialUrlOutput,
                schema_name="school_official_urls",
                max_output_tokens=2400,
                max_search_uses=len(batch),
            )
        except HTTPException as error:
            logger.warning(
                "school_url_search_failed offset=%s status=%s",
                offset,
                error.status_code,
            )
            return {}
        return {item.index: item.school_official_url for item in result.schools}

    batches = [
        (offset, universities[offset : offset + SCHOOL_URL_BATCH_SIZE])
        for offset in range(0, len(universities), SCHOOL_URL_BATCH_SIZE)
    ]
    batch_results = await asyncio.gather(
        *(enrich_batch(offset, batch) for offset, batch in batches)
    )
    urls = {index: url for result in batch_results for index, url in result.items()}
    return [
        university.model_copy(update={"school_official_url": urls.get(index)})
        for index, university in enumerate(universities)
    ]


async def enrich_school_official_urls_cached(
    universities: List[CandidateUniversity],
    *,
    force_refresh: bool = False,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> List[CandidateUniversity]:
    """Reuse long-lived school homepage metadata and search only cache misses."""
    if not universities:
        return universities

    resolved: Dict[int, str] = {}
    cached_fallback: Dict[int, str] = {}
    search_indices: List[int] = []
    for index, university in enumerate(universities):
        key = university_cache_key(university.university, university.country)
        cached_url = cache.read_university_official_url(key)
        if cached_url:
            cached_fallback[index] = cached_url
        if cached_url and not force_refresh:
            resolved[index] = cached_url
        else:
            search_indices.append(index)

    if search_indices:
        searched = await enrich_school_official_urls(
            [universities[index] for index in search_indices]
        )
        for original_index, enriched in zip(search_indices, searched):
            university = universities[original_index]
            key = university_cache_key(university.university, university.country)
            if enriched.school_official_url:
                resolved[original_index] = enriched.school_official_url
                try:
                    cache.write_university_official_url(
                        key,
                        university.university,
                        university.country,
                        enriched.school_official_url,
                    )
                except (OSError, sqlite3.Error) as error:
                    logger.warning("university_url_cache_write_failed key=%s error=%s", key, error)
            elif original_index in cached_fallback:
                resolved[original_index] = cached_fallback[original_index]

    logger.info(
        "university_url_cache_result total=%d hits=%d searches=%d force_refresh=%s",
        len(universities),
        len(universities) - len(search_indices),
        len(search_indices),
        force_refresh,
    )
    return [
        university.model_copy(update={"school_official_url": resolved.get(index)})
        for index, university in enumerate(universities)
    ]


async def discover_candidate_universities(
    target: ExploreTargetRequest,
) -> CandidateUniversityResult:
    """Preserve the original live discovery function for direct callers and tests."""
    result = await _filter_candidate_universities(target)
    return result.model_copy(
        update={"universities": await enrich_school_official_urls(result.universities)}
    )


async def discover_candidate_universities_cached(
    target: ExploreTargetRequest,
    *,
    force_refresh: bool = False,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> CandidateUniversityResult:
    result = await _filter_candidate_universities(target)
    return result.model_copy(
        update={
            "universities": await enrich_school_official_urls_cached(
                result.universities,
                force_refresh=force_refresh,
                cache=cache,
            )
        }
    )


@app.post(
    "/candidate-universities/discover",
    response_model=CandidateUniversityResult,
    tags=["programs"],
)
async def discover_candidate_universities_endpoint(
    target: ExploreTargetRequest,
    force_refresh: bool = Query(default=False),
) -> CandidateUniversityResult:
    return await discover_candidate_universities_cached(
        target,
        force_refresh=force_refresh,
    )


async def discover_candidate_programs(
    request: UniversityProgramRequest,
) -> CandidateProgramResult:
    """Let one search-enabled model discover and judge relevant master's programmes."""
    university = request.university
    target = request.target
    prompt = (
        "Use Web Search to discover up to five current master's programmes at the target "
        "university that are semantically relevant to the user's intended field and "
        "preferences. Decide which programme pages and URLs are correct yourself. Prefer "
        "official university sources, return the programme's actual name and canonical "
        "programme page URL, and include a short degree type and relevance reason. Do not "
        "use exact-keyword, title-pattern, or URL-pattern matching. If a fact is uncertain, "
        "omit that programme rather than inventing it. Return only the structured result.\n\n"
        f"University: {university.university}\n"
        f"Country or region: {university.country}\n"
        f"School homepage reference: {university.school_official_url or 'unknown'}\n"
        f"Intended field: {target.target_major}\n"
        f"Additional preferences: {target.additional_preferences or 'none'}"
    )
    result = await call_deepseek_web_search(
        prompt,
        ProgramDiscoveryWebSearchOutput,
        schema_name="candidate_programs",
        max_output_tokens=3600,
    )
    return CandidateProgramResult(
        candidates=[
            CandidateProgram(
                university=university.university,
                program=item.program,
                country=university.country,
                ranking=university.ranking,
                ranking_system="QS",
                ranking_edition=university.ranking_edition,
                ranking_source_url=university.ranking_source_url,
                official_program_url=item.official_program_url,
                degree_type=item.degree_type,
                relevance_reason=item.relevance_reason,
            )
            for item in result.programs
        ]
    )


def normalized_programme_query(target: ExploreTargetRequest) -> str:
    return re.sub(
        r"\s+",
        " ",
        f"{target.target_major} {target.additional_preferences}".strip().casefold(),
    )


def programme_relevance_score(
    record: ProgrammePoolRecord,
    target: ExploreTargetRequest,
) -> tuple[int, int, int, int]:
    query = normalized_programme_query(target)
    target_major = re.sub(r"\s+", " ", target.target_major.strip().casefold())
    haystack = " ".join(
        (
            record.programme,
            record.degree_type,
            record.relevance_reason,
        )
    ).casefold()
    query_history = record.source_metadata.get("queries", [])
    exact_history = int(query in query_history)
    phrase_match = int(bool(target_major) and target_major in haystack)
    query_tokens = set(re.findall(r"[\w]+", query, flags=re.UNICODE))
    haystack_tokens = set(re.findall(r"[\w]+", haystack, flags=re.UNICODE))
    token_overlap = len(query_tokens & haystack_tokens)
    return (exact_history, phrase_match, token_overlap, -record.discovery_order)


def candidate_programmes_from_pool(
    request: UniversityProgramRequest,
    records: List[ProgrammePoolRecord],
    *,
    refresh_scheduled: bool = False,
) -> CandidateProgramResult:
    university = request.university
    ranked = sorted(
        records,
        key=lambda item: programme_relevance_score(item, request.target),
        reverse=True,
    )[:5]
    return CandidateProgramResult(
        candidates=[
            CandidateProgram(
                university=university.university,
                program=item.programme,
                country=university.country,
                ranking=university.ranking,
                ranking_system="QS",
                ranking_edition=university.ranking_edition,
                ranking_source_url=university.ranking_source_url,
                official_program_url=item.official_program_url,
                degree_type=item.degree_type,
                relevance_reason=item.relevance_reason,
            )
            for item in ranked
        ],
        cache_source="programme_pool",
        refresh_scheduled=refresh_scheduled,
    )


async def refresh_school_programme_pool(
    request: UniversityProgramRequest,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> CandidateProgramResult:
    """Run the existing live discovery once and incrementally merge successful output."""
    live_result = await discover_candidate_programs(request)
    university = request.university
    key = university_cache_key(university.university, university.country)
    try:
        cache.merge_programme_pool(
            key,
            university.university,
            [item.model_dump(mode="json") for item in live_result.candidates],
            {
                "source": "deepseek_web_search",
                "queries": [normalized_programme_query(request.target)],
                "school_official_url": university.school_official_url,
            },
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        logger.warning("programme_pool_merge_failed key=%s error=%s", key, error)
    return live_result


async def refresh_school_programme_pool_background(
    request: UniversityProgramRequest,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> None:
    try:
        await refresh_school_programme_pool(request, cache)
    except HTTPException as error:
        logger.warning(
            "programme_pool_background_refresh_failed university=%r status=%s",
            request.university.university,
            error.status_code,
        )


async def discover_candidate_programs_cached(
    request: UniversityProgramRequest,
    *,
    force_refresh: bool = False,
    background_tasks: Optional[BackgroundTasks] = None,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> CandidateProgramResult:
    university = request.university
    key = university_cache_key(university.university, university.country)
    snapshot = cache.read_programme_pool(key)

    if force_refresh:
        await refresh_school_programme_pool(request, cache)
        refreshed = cache.read_programme_pool(key)
        if refreshed.programmes:
            return candidate_programmes_from_pool(request, refreshed.programmes)
        return CandidateProgramResult(candidates=[])

    if snapshot.programmes:
        if snapshot.fresh:
            logger.info("programme_pool_hit university=%r fresh=true", university.university)
            return candidate_programmes_from_pool(request, snapshot.programmes)
        scheduled = background_tasks is not None
        if background_tasks is not None:
            background_tasks.add_task(refresh_school_programme_pool_background, request, cache)
        logger.info(
            "programme_pool_hit university=%r fresh=false refresh_scheduled=%s",
            university.university,
            scheduled,
        )
        return candidate_programmes_from_pool(
            request,
            snapshot.programmes,
            refresh_scheduled=scheduled,
        )

    live_result = await refresh_school_programme_pool(request, cache)
    if not live_result.candidates:
        return live_result
    refreshed = cache.read_programme_pool(key)
    if refreshed.programmes:
        return candidate_programmes_from_pool(request, refreshed.programmes)
    return live_result


@app.post(
    "/candidate-programs/discover",
    response_model=CandidateProgramResult,
    tags=["programs"],
)
async def discover_candidate_programs_endpoint(
    request: UniversityProgramRequest,
    background_tasks: BackgroundTasks,
    force_refresh: bool = Query(default=False),
) -> CandidateProgramResult:
    return await discover_candidate_programs_cached(
        request,
        force_refresh=force_refresh,
        background_tasks=background_tasks,
    )


async def confirm_target_program(
    request: TargetProgramConfirmationRequest,
) -> TargetProgram:
    """Normalize a model-selected programme or identify a manually supplied URL."""
    university = request.university.strip()
    program = request.program.strip()
    program_url = request.official_program_url.strip()
    if not university:
        raise HTTPException(status_code=422, detail="请提供学校名称。")

    if not program or not program_url:
        prompt = (
            "Use Web Search to identify the specific master's programme described below. "
            "Decide the programme identity and canonical programme page yourself. Prefer "
            "the university's official source. Return only a programme name and URL; do not "
            "invent missing facts.\n\n"
            f"University: {university}\n"
            f"Programme name if supplied: {program or 'unknown'}\n"
            f"Programme URL if supplied: {program_url or 'unknown'}"
        )
        result = await call_deepseek_web_search(
            prompt,
            TargetProgramLookupOutput,
            schema_name="target_program",
            max_output_tokens=1600,
        )
        program = result.program
        program_url = result.official_program_url

    return TargetProgram(
        university=university,
        program=program,
        official_program_url=program_url,
        official_domain=(urlparse(program_url).hostname or ""),
    )


@app.post(
    "/target-programs/confirm",
    response_model=TargetProgram,
    tags=["programs"],
)
async def confirm_target_program_endpoint(
    request: TargetProgramConfirmationRequest,
) -> TargetProgram:
    try:
        return await asyncio.wait_for(
            confirm_target_program(request),
            timeout=TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="项目确认超时，请重试。") from error


class OfficialProgrammePageTextParser(HTMLParser):
    hidden_tags = {"script", "style", "noscript", "svg", "template"}
    block_tags = {
        "article",
        "aside",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.blocks: List[str] = []
        self.current: List[str] = []

    def flush(self) -> None:
        text = re.sub(r"\s+", " ", " ".join(self.current)).strip()
        if text:
            self.blocks.append(text)
        self.current = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        lowered = tag.casefold()
        if lowered in self.hidden_tags:
            self.hidden_depth += 1
        elif lowered in self.block_tags and self.hidden_depth == 0:
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self.hidden_tags:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif lowered in self.block_tags and self.hidden_depth == 0:
            self.flush()

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0 and data.strip():
            self.current.append(data.strip())

    def text(self) -> str:
        self.flush()
        full_text = "\n".join(self.blocks)
        if len(full_text) <= OFFICIAL_PROGRAM_PAGE_MAX_CHARS:
            return full_text

        section_markers = re.compile(
            r"entry requirements?|admissions?|how to apply|supporting documents?|"
            r"portfolio|personal statement|statement of purpose|english language|"
            r"qualifications?|eligibility|references?|transcripts?|application video",
            re.IGNORECASE,
        )
        selected_indexes = set(range(min(80, len(self.blocks))))
        for index, block in enumerate(self.blocks):
            if section_markers.search(block):
                selected_indexes.update(
                    range(max(0, index - 3), min(len(self.blocks), index + 31))
                )
        selected = "\n".join(
            self.blocks[index] for index in sorted(selected_indexes)
        )
        return selected[:OFFICIAL_PROGRAM_PAGE_MAX_CHARS]


async def ensure_public_direct_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=502, detail="Official programme URL is not fetchable")
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise HTTPException(status_code=502, detail="Official programme URL is not public")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        if not literal_address.is_global:
            raise HTTPException(status_code=502, detail="Official programme URL is not public")
        return
    try:
        loop = asyncio.get_running_loop()
        addresses = await loop.run_in_executor(
            None,
            partial(
                socket.getaddrinfo,
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ),
        )
    except OSError as error:
        raise HTTPException(
            status_code=502,
            detail="Unable to resolve official programme URL",
        ) from error
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise HTTPException(status_code=502, detail="Official programme URL is not public")


async def fetch_official_program_page_text(url: str) -> str:
    current_url = url.strip()
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=OFFICIAL_PROGRAM_PAGE_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": "UniversityApplyPlan/1.0 Requirements fallback"},
    ) as client:
        for redirect_count in range(OFFICIAL_PROGRAM_PAGE_MAX_REDIRECTS + 1):
            await ensure_public_direct_fetch_url(current_url)
            try:
                response = await client.get(current_url)
            except httpx.TimeoutException as error:
                raise HTTPException(
                    status_code=504,
                    detail="Official programme page fetch timed out",
                ) from error
            except httpx.RequestError as error:
                raise HTTPException(
                    status_code=502,
                    detail="Unable to fetch official programme page",
                ) from error
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= OFFICIAL_PROGRAM_PAGE_MAX_REDIRECTS:
                    raise HTTPException(
                        status_code=502,
                        detail="Official programme page redirect could not be followed",
                    )
                current_url = urljoin(current_url, location)
                continue
            if response.is_error:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Official programme page returned HTTP "
                        f"{response.status_code}"
                    ),
                )
            content_type = response.headers.get("content-type", "").casefold()
            if "html" not in content_type and "text" not in content_type:
                raise HTTPException(
                    status_code=502,
                    detail="Official programme page did not return HTML text",
                )
            parser = OfficialProgrammePageTextParser()
            parser.feed(response.text)
            page_text = parser.text().strip()
            if not page_text:
                raise HTTPException(
                    status_code=502,
                    detail="Official programme page contained no readable text",
                )
            return page_text
    raise HTTPException(status_code=502, detail="Official programme page fetch failed")


REQUIREMENTS_TEMPORAL_CONTRACT = (
    "TEMPORAL APPLICABILITY CONTRACT — read intended_entry_year and intended_entry_term from "
    "the supplied target programme and classify every Requirement independently from its "
    "provenance:\n"
    "- If the official page explicitly covers the target entry cycle, use "
    "temporal_applicability=target_cycle_confirmed and record the explicit source_cycle.\n"
    "- If the current official page gives no explicit year or entry cycle, use "
    "temporal_applicability=undated and source_cycle=null. Do not invent a cycle.\n"
    "- If the page explicitly belongs to a different application or entry cycle, use "
    "temporal_applicability=previous_cycle and record source_cycle. It may be returned as a "
    "reference, but must not be described as confirmed for the target cycle.\n"
    "- If the page explicitly says the target-cycle information has not yet been published and "
    "there is no current-cycle Requirement to extract, use "
    "temporal_applicability=not_yet_published and explain this in temporal_note.\n"
    "- If cycle labels conflict or applicability cannot be determined, use "
    "temporal_applicability=unknown and explain the uncertainty in temporal_note.\n"
    "Official provenance and temporal applicability are orthogonal. Keep official facts from a "
    "previous cycle as verification_status=official_verified; never downgrade them to "
    "model_memory_unverified merely because their cycle differs."
)

REQUIREMENTS_IMPORTANCE_CONTRACT = (
    "IMPORTANCE ENUM CONTRACT:\n"
    "- importance must be exactly one of: required, recommended, preferred, unknown.\n"
    "- The phrase conditional-required describes extraction priority only; "
    "conditional_required is not a valid importance value.\n"
    "- For a conditional Requirement, output importance=required and preserve the complete "
    "applicability condition in the requirement text.\n"
)

REQUIREMENTS_APPLICABILITY_STAGE_CONTRACT = (
    "ADMISSION-STAGE APPLICABILITY CONTRACT — for every extracted Requirement determine WHEN "
    "the applicant or student must satisfy it. applicability_stage must be exactly one of "
    "pre_admission, conditional_admission, in_program, informational, unclear. This dimension "
    "is independent from verification_status and temporal_applicability.\n"
    "- pre_admission: an applicant must already satisfy it or submit it to apply or be eligible "
    "for admission, including degree/GPA eligibility, undergraduate prerequisites, tests, and "
    "application documents.\n"
    "- conditional_admission: an admission/application rule applies only when an explicit "
    "applicant condition holds, including waivers or exemptions. Preserve the condition.\n"
    "- in_program: it is completed after enrollment as part of the master's curriculum, degree, "
    "progression, or graduation requirements.\n"
    "- informational: true programme information such as tuition, funding, duration, location, "
    "or processing information, but not an applicant qualification or submission requirement.\n"
    "- unclear: the available official context cannot reliably establish when it applies. Never "
    "upgrade unclear to pre_admission.\n"
    "Use page title, section heading, nearby preceding/following sentences, and applicant versus "
    "student/curriculum wording. A heading named Program Requirements or Requirements is not "
    "proof of admission applicability. Words such as must, required, pass, or complete also do "
    "not imply pre_admission: a mandatory rule can be in_program. Master's curriculum credits "
    "or units, electives, qualifying units, performance maintained after enrollment, thesis or "
    "capstone, and graduation rules strongly signal in_program. Applicant, application, "
    "eligibility, before admission, undergraduate prerequisite, and documents to submit strongly "
    "signal pre_admission. Do not classify every course rule as in_program: undergraduate work "
    "an applicant must complete before admission is pre_admission.\n"
    "Example — a Program Requirements section says: pass 96-108 units in qualifying master's "
    "courses; pass one course from each of Systems, Theoretical Foundations, and Artificial "
    "Intelligence; maintain a 3.0 QPA. Each item is in_program because it concerns coursework, "
    "units, and academic performance after enrollment, not an applicant's prior qualification."
)


async def extract_requirements_from_official_program_page(
    target_program: TargetProgram,
) -> RequirementsExtraction:
    page_text = await fetch_official_program_page_text(
        target_program.official_program_url
    )
    prompt = (
        "Prioritize extracting admission/application Requirements from the supplied official "
        "programme page "
        "text. Do not use Web Search, model memory, or facts not explicitly supported by the "
        "page context. Look for Entry requirements, Admissions, How to apply, Supporting "
        "documents, Portfolio, Personal statement, application video, English language, "
        "academic eligibility, and other application requirements. Return partial coverage "
        "when only some requirements are present; return requirements=[] only when the supplied "
        "page text contains no extractable application Requirement. If the inspected page also "
        "contains genuine in-program or informational programme statements, preserve them with "
        "the correct applicability_stage instead of presenting them as admission requirements.\n\n"
        "EXTRACTION PRIORITY AND COMPLETENESS RULES:\n"
        "- Select and order items by this fixed priority: required eligibility and required "
        "application materials first; then conditional-required items; then recommended or "
        "preferred items; and finally administrative or contextual information. Never let an "
        "optional, administrative, or contextual item displace an independent required or "
        "conditional-required item.\n"
        "- Before finishing, inventory every mandatory supporting document actually named by "
        "the supplied official page. Check for transcripts, degree certificates, CVs or "
        "resumes, references or recommendation letters, statements, portfolios or work "
        "samples, identification documents, and programme-specific forms, sheets, or "
        "questionnaires, as well as other mandatory application documents. These are generic "
        "document types, not an exhaustive list. A materials category containing one item is "
        "not evidence that the inventory is complete.\n"
        "- Also check academic and course eligibility, standardized or language requirements, "
        "experience requirements, and conditional applicability. Include every independent "
        "required item actually present, preserving quantities, word/page/time limits, scores, "
        "component thresholds, exceptions, and AND/OR conditions. Do not merge or omit separate "
        "required materials merely to shorten the response.\n"
        "- There is no numeric item limit for required or conditional-required Requirements. "
        "Return every supported item at those priorities. Keep recommended/preferred items "
        "concise, and include at most three low-priority administrative/contextual items after "
        "all higher-priority items. Application deadlines, opening dates, and application-cycle "
        "dates belong to Timeline Retrieval and must not be returned as Requirements. Each item "
        "must include an English requirement and a faithful concise Chinese requirement_zh.\n\n"
        f"{REQUIREMENTS_IMPORTANCE_CONTRACT}\n"
        f"{REQUIREMENTS_TEMPORAL_CONTRACT}\n\n"
        f"{REQUIREMENTS_APPLICABILITY_STAGE_CONTRACT}\n\n"
        "For every extracted item set "
        "source_level=program, source_type=official_retrieval, "
        "verification_status=official_verified, and source_url to the supplied exact official "
        "programme URL. Return only JSON.\n\n"
        f"Target programme: {target_program.model_dump_json()}\n"
        f"Output JSON Schema: {json.dumps(RequirementsExtraction.model_json_schema(), ensure_ascii=False)}\n\n"
        "OFFICIAL PROGRAMME PAGE TEXT:\n"
        f"{page_text}"
    )
    content = await call_deepseek(
        messages=[
            {
                "role": "system",
                "content": "Extract only Requirements supported by the provided official page text.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=7000,
        response_format={"type": "json_object"},
    )
    try:
        extraction = RequirementsExtraction.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek returned invalid direct-fetch Requirements data",
        ) from error
    normalized = [
        item.model_copy(
            update={
                "source_level": "program",
                "source_type": "official_retrieval",
                "verification_status": "official_verified",
                "source_url": target_program.official_program_url,
            }
        )
        for item in normalize_extracted_applicability_stages(extraction.requirements)
    ]
    return RequirementsExtraction(requirements=normalized)


async def retrieve_target_program_requirements(
    target_program: TargetProgram,
) -> TargetProgramRequirementsReview:
    """Retrieve one official-first, best-effort Requirements snapshot."""
    output_example = {
        "requirements": [
            {
                "category": "language",
                "requirement": "IELTS 7.0 overall is required.",
                "requirement_zh": "IELTS 总分须达到 7.0。",
                "importance": "required",
                "source_level": "program",
                "source_type": "official_retrieval",
                "verification_status": "official_verified",
                "source_url": "https://university.example/program/requirements",
                "source_cycle": "Fall 2027",
                "temporal_applicability": "target_cycle_confirmed",
                "temporal_note": None,
                "applicability_stage": "pre_admission",
            },
            {
                "category": "materials",
                "requirement": "A portfolio may be required.",
                "requirement_zh": "可能需要提交作品集。",
                "importance": "unknown",
                "source_level": "unknown",
                "source_type": "model_memory",
                "verification_status": "model_memory_unverified",
                "source_url": None,
                "source_cycle": None,
                "temporal_applicability": "unknown",
                "temporal_note": "The applicable entry cycle could not be confirmed.",
                "applicability_stage": "unclear",
            }
        ],
        "search_audit": {
            "search_attempts_completed": 2,
            "programme_page_checked": True,
            "sections_checked": [
                "Entry requirements",
                "Supporting documents",
                "English language requirements",
            ],
            "programme_page_has_no_extractable_requirements": False,
            "empty_result_reason": None,
        },
    }
    prompt = (
        "Use Web Search to answer this admission-oriented question for the exact master's "
        "programme: What must an applicant satisfy or submit in order to apply or be eligible "
        "for admission? Cover academic, course, language, standardized_test, experience, "
        "materials, and other application requirements when evidence exists. Do not use "
        "programme/degree/curriculum requirements as substitutes for admission requirements. "
        "If genuine non-admission requirements are encountered while inspecting the same official "
        "sources, preserve them with the correct applicability_stage rather than relabeling them "
        "as admission requirements.\n\n"
        "SECTION-LEVEL SEARCH CONTRACT — use at most two Web Search calls and keep all credible "
        "requirements found across both results:\n"
        "1. When official_program_url is known, the first search must be anchored to that exact "
        "URL, exact programme name, and official domain. Prioritize queries equivalent to exact "
        "programme name + admission requirements / application requirements / eligibility / "
        "how to apply / prerequisites / required documents / graduate admissions. Its search "
        "intent must cover Entry requirements / Admissions / How to apply / Portfolio / "
        "Supporting documents. Do not use exact programme name + program requirements as the "
        "primary admission query. Treat "
        "the programme page as the mandatory primary source. Inspect headings, anchors, tabs, "
        "accordions, and sections below the overview; an overview-only hit is not sufficient.\n"
        "2. After the first result, assess the accumulated programme-level evidence. If it is "
        "empty, overview-only, missing likely application sections, or the mandatory supporting-"
        "document inventory is still clearly incomplete, you must use the second search before "
        "returning. Finding one materials item does not make supporting-document coverage "
        "complete. Anchor the second search again to the exact programme name and official "
        "domain, targeting the missing Entry requirements / Admissions / How to apply / "
        "Supporting documents / Application checklist / programme-specific application "
        "requirements / Portfolio / English language requirements sections. The "
        "second search supplements the first; it must not discard requirements already found.\n"
        "After the second result, or sooner only when programme-level coverage is sufficient, "
        "stop searching and immediately output the complete JSON. Never pursue exhaustive "
        "search.\n\n"
        "EMPTY-RESULT GATE:\n"
        "- Do not return requirements=[] merely because one search did not directly surface a "
        "section. If the first result is insufficient, perform the second section-focused "
        "search.\n"
        "- requirements=[] is allowed only when both search attempts still provide no "
        "sufficiently credible requirement information, or when the target programme page "
        "itself clearly has no extractable application requirements.\n"
        "- If any credible programme-level requirement is found, output every confirmed item. "
        "Partial coverage is valid and preferred over discarding the entire result because "
        "other sections remain incomplete.\n\n"
        "EXTRACTION PRIORITY AND COMPLETENESS RULES:\n"
        "- Select and order items by this fixed priority: required eligibility and required "
        "application materials first; then conditional-required items; then recommended or "
        "preferred items; and finally administrative or contextual information. Never let an "
        "optional, administrative, or contextual item displace an independent required or "
        "conditional-required item.\n"
        "- Before finishing, inventory every mandatory supporting document actually named by "
        "the official sources. Check for transcripts, degree certificates, CVs or resumes, "
        "references or recommendation letters, statements, portfolios or work samples, "
        "identification documents, and programme-specific forms, sheets, or questionnaires, "
        "as well as other mandatory application documents. These are generic document types, "
        "not an exhaustive list. A materials category containing one item is not evidence that "
        "the inventory is complete.\n"
        "- Also check academic and course eligibility, standardized or language requirements, "
        "experience requirements, and conditional applicability. Include every independent "
        "required item actually present, preserving quantities, word/page/time limits, scores, "
        "component thresholds, exceptions, and AND/OR conditions. Do not merge or omit separate "
        "required materials merely to shorten the response.\n"
        "- Facts found on the exact programme page are programme-level official evidence: use "
        "source_type=official_retrieval, verification_status=official_verified, "
        "source_level=program, and that exact page as source_url. Other current official pages "
        "use their applicable source level and URL.\n"
        "- If official information is blocked, inaccessible, incomplete, or available only in "
        "a search summary, use the existing ai_reference mechanism for a reasonable cautious "
        "reference: source_type=model_memory, verification_status=model_memory_unverified, "
        "source_level=unknown, normally importance=unknown, and source_url=null unless a useful "
        "reference URL exists. Never present it as confirmed official fact.\n"
        "- Only omit a category when neither official evidence nor a reasonable AI reference "
        "exists. Do not invent facts or infer that an unmentioned item is not required.\n"
        "- There is no numeric item limit for required or conditional-required Requirements. "
        "Return every supported item at those priorities. Keep recommended/preferred items "
        "concise, and include at most three low-priority administrative/contextual items after "
        "all higher-priority items. Application deadlines, opening dates, and application-cycle "
        "dates belong to Timeline Retrieval and must not be returned as Requirements. Each item "
        "must include an English requirement and a faithful concise Chinese requirement_zh.\n\n"
        f"{REQUIREMENTS_IMPORTANCE_CONTRACT}\n"
        f"{REQUIREMENTS_TEMPORAL_CONTRACT}\n\n"
        f"{REQUIREMENTS_APPLICABILITY_STAGE_CONTRACT}\n\n"
        "SEARCH AUDIT OUTPUT:\n"
        "- search_audit.search_attempts_completed must report how many of the allowed searches "
        "were actually completed.\n"
        "- programme_page_checked is true only when the exact programme URL or an exact-page "
        "search result was examined. sections_checked lists the application section names "
        "actually sought.\n"
        "- programme_page_has_no_extractable_requirements may be true only when available "
        "evidence affirmatively indicates that the target page has no extractable application "
        "requirements; failure to surface a section in one search is not enough.\n"
        "- When requirements is empty, empty_result_reason is mandatory and must explain why "
        "the two-search gate or confirmed no-requirements condition was satisfied.\n\n"
        "Return a complete final JSON even when sparse. Do not narrate searches, failures, or "
        "reasoning outside the structured search_audit. Return only one JSON "
        "object shaped exactly like this example:\n"
        f"{json.dumps(output_example, ensure_ascii=False)}\n\n"
        f"Target programme: {json.dumps(target_program.model_dump(), ensure_ascii=False)}"
    )
    try:
        result = await call_deepseek_web_search(
            prompt,
            RequirementsWebSearchOutput,
            schema_name="program_requirements",
            max_output_tokens=14000,
            max_search_uses=2,
        )
    except DeepSeekWebSearchNoFinalTextError:
        if not target_program.official_program_url.strip():
            raise
        logger.warning(
            "requirements_search_no_final_text_using_direct_fetch program=%r url=%s",
            target_program.program,
            target_program.official_program_url,
        )
        result = RequirementsWebSearchOutput(requirements=[])
    audit = result.search_audit
    result = result.model_copy(
        update={
            "requirements": normalize_extracted_applicability_stages(
                result.requirements
            )
        }
    )
    logger.info(
        "requirements_section_recall program=%r search_attempts=%s programme_page_checked=%s "
        "sections_checked=%s requirement_count=%d",
        target_program.program,
        audit.search_attempts_completed if audit else "unreported",
        audit.programme_page_checked if audit else "unreported",
        audit.sections_checked if audit else [],
        len(result.requirements),
    )
    if not result.requirements:
        empty_allowed = (
            audit is not None
            and (
                audit.search_attempts_completed == 2
                or (
                    audit.programme_page_checked
                    and audit.programme_page_has_no_extractable_requirements
                )
            )
        )
        contract_error: Optional[HTTPException] = None
        if not empty_allowed:
            contract_error = HTTPException(
                status_code=502,
                detail=(
                    "DeepSeek Requirements search ended empty before completing the "
                    "section-level recall contract"
                ),
            )
        elif audit is None or not audit.empty_result_reason:
            contract_error = HTTPException(
                status_code=502,
                detail="DeepSeek Requirements search returned an unjustified empty result",
            )
        if contract_error is not None:
            if not target_program.official_program_url.strip():
                raise contract_error
            fallback_started = datetime.now(timezone.utc)
            logger.info(
                "requirements_direct_fetch_fallback_triggered program=%r url=%s",
                target_program.program,
                target_program.official_program_url,
            )
            try:
                fallback = await extract_requirements_from_official_program_page(
                    target_program
                )
            except Exception as error:
                logger.warning(
                    "requirements_direct_fetch_fallback_failed program=%r error=%s",
                    target_program.program,
                    safe_error_message(error, os.getenv("DEEPSEEK_API_KEY", "")),
                )
                raise contract_error from error
            if not fallback.requirements:
                logger.warning(
                    "requirements_direct_fetch_fallback_empty program=%r",
                    target_program.program,
                )
                raise contract_error
            logger.info(
                "requirements_direct_fetch_fallback_succeeded program=%r count=%d elapsed_seconds=%.3f",
                target_program.program,
                len(fallback.requirements),
                (datetime.now(timezone.utc) - fallback_started).total_seconds(),
            )
            return requirements_review_from_extraction(target_program, fallback)
    extraction = RequirementsExtraction(requirements=result.requirements)
    return requirements_review_from_extraction(target_program, extraction)


def target_program_cache_identity(target_program: TargetProgram) -> Dict[str, Any]:
    return normalized_programme_identity(
        university=target_program.university,
        programme=target_program.program,
        official_program_url=target_program.official_program_url,
        intended_entry_year=target_program.intended_entry_year,
        intended_entry_term=target_program.intended_entry_term,
    )


def timeline_cache_identity(request: ApplicationTimelineRequest) -> Dict[str, Any]:
    return normalized_programme_identity(
        university=request.university,
        programme=request.program_name,
        official_program_url=request.official_program_url,
        intended_entry_year=request.intended_entry_year,
        intended_entry_term=request.intended_entry_term,
    )


async def retrieve_target_program_requirements_cached(
    target_program: TargetProgram,
    *,
    force_refresh: bool = False,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> TargetProgramRequirementsReview:
    """Read runtime/seed snapshots before invoking the unchanged live workflow."""
    identity = target_program_cache_identity(target_program)
    cache_key = programme_cache_key(identity)
    semantic_key = programme_semantic_cache_key(identity)
    if not force_refresh:
        records = (
            (
                "runtime_cache",
                cache.read_runtime(
                    "requirements",
                    cache_key,
                    semantic_key=semantic_key,
                ),
            ),
            ("seed", cache.read_seed("requirements", cache_key)),
        )
        for source, record in records:
            if record is None:
                continue
            try:
                review = TargetProgramRequirementsReview.model_validate(record.payload)
            except ValidationError as error:
                logger.warning(
                    "programme_cache_payload_invalid kind=requirements source=%s key=%s error=%s",
                    source,
                    cache_key,
                    error,
                )
                continue
            logger.info("programme_cache_hit kind=requirements source=%s key=%s", source, cache_key)
            return review.model_copy(
                update={
                    "target_program": target_program,
                    "checked_at": record.checked_at,
                    "cache_source": source,
                }
            )

    review = await retrieve_target_program_requirements(target_program)
    review = review.model_copy(update={"cache_source": "live"})
    has_requirements = any(category.requirements for category in review.categories)
    if has_requirements:
        try:
            cache.write_runtime(
                "requirements",
                cache_key,
                review.checked_at,
                review.model_dump(mode="json"),
                semantic_key=semantic_key,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            logger.warning(
                "programme_cache_runtime_write_failed kind=requirements key=%s error=%s",
                cache_key,
                error,
            )
    logger.info("programme_cache_result kind=requirements source=live key=%s", cache_key)
    return review


def requirements_review_from_extraction(
    target_program: TargetProgram,
    extraction: RequirementsExtraction,
) -> TargetProgramRequirementsReview:
    """Map model provenance to the compatible category coverage contract."""
    grouped: Dict[str, List[RequirementItem]] = {
        category: [] for category in REQUIREMENT_CATEGORIES
    }
    for requirement in extraction.requirements:
        grouped[requirement.category].append(requirement)

    categories: List[RequirementCategoryReview] = []
    for category in REQUIREMENT_CATEGORIES:
        items = grouped[category]
        if any(item.verification_status == "official_verified" for item in items):
            coverage: RequirementCoverage = "official_verified"
        elif items:
            coverage = "model_memory_unverified"
        else:
            coverage = "not_found"
        categories.append(
            RequirementCategoryReview(
                category=category,
                coverage=coverage,
                requirements=items,
            )
        )
    return TargetProgramRequirementsReview(
        target_program=target_program,
        checked_at=datetime.now(timezone.utc).isoformat(),
        categories=categories,
    )


@app.post(
    "/target-programs/requirements",
    response_model=TargetProgramRequirementsReview,
    tags=["programs"],
)
async def target_program_requirements_endpoint(
    target_program: TargetProgram,
    force_refresh: bool = Query(default=False),
) -> TargetProgramRequirementsReview:
    try:
        return await asyncio.wait_for(
            retrieve_target_program_requirements_cached(
                target_program,
                force_refresh=force_refresh,
            ),
            timeout=REQUIREMENTS_TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="项目要求获取超时，请重试。") from error


def normalize_application_timeline(
    timeline: ApplicationTimeline,
) -> ApplicationTimeline:
    """Derive status only from structured field completeness, not date truth."""
    if timeline.application_open_date and timeline.application_deadlines:
        status: Literal["complete", "partial", "not_found"] = "complete"
    elif (
        timeline.application_open_date
        or timeline.application_deadlines
        or timeline.rolling_admission is not None
    ):
        status = "partial"
    else:
        status = "not_found"
    return timeline.model_copy(update={"status": status})


async def retrieve_application_timeline(
    request: ApplicationTimelineRequest,
) -> ApplicationTimeline:
    """Retrieve current official application dates in one search-enabled request."""
    output_example = {
        "admission_cycle": "Fall 2027",
        "application_open_date": "2026-09-15",
        "application_open_source_url": "https://university.example/admissions",
        "application_deadlines": [
            {
                "label": "Round 1",
                "type": "round",
                "date": "2026-12-01",
                "source_url": "https://university.example/program/deadlines",
            },
            {
                "label": "Final deadline",
                "type": "final",
                "date": "2027-03-01",
                "source_url": "https://university.example/program/deadlines",
            },
        ],
        "rolling_admission": False,
        "rolling_admission_source_url": "https://university.example/program/deadlines",
        "status": "complete",
    }
    prompt = (
        "Use Web Search to retrieve the current official application timeline for the exact "
        "target programme and intended entry cycle below. Use only current official "
        "university information. Do not use model memory, historical assumptions, third-party "
        "dates, or AI reference dates. If a date cannot be supported by a current official "
        "source, return null or omit the deadline. If the requested future entry cycle has not "
        "yet been published, set status=not_found and return no dates. Never reuse or relabel "
        "dates from another entry year or term as dates for the requested cycle.\n\n"
        "Search in this semantic priority: the official programme page, then the official "
        "department page, then the university's official graduate admissions page. You decide "
        "which pages are applicable; the backend will not verify or rerank them. Keep every "
        "application submission deadline for this programme and cycle, including Round 1, "
        "Round 2, priority, standard, and final deadlines. Do not collapse multiple rounds into "
        "one deadline.\n\n"
        "Only include dates for submitting the programme application. Never treat scholarship, "
        "financial aid, visa, housing, enrollment, orientation, offer acceptance, or decision "
        "release dates as application deadlines. rolling_admission may be true or false only "
        "when a current official source explicitly says so; otherwise use null.\n\n"
        "For date fields, use ISO YYYY-MM-DD only when the official source explicitly gives a "
        "complete calendar date. If the official source only says a month or approximate period "
        "such as 'opens in September', preserve that wording and do not invent a day such as "
        "September 1. Every returned deadline must include the official source URL that supports "
        "it. Include official source URLs for the opening date and rolling-admission statement "
        "when available.\n\n"
        "Set status=complete when both an opening date and at least one deadline are available; "
        "status=partial when only some official timeline information is available; and "
        "status=not_found when no official opening date, application deadline, or explicit "
        "rolling-admission status can be found. Do not narrate the research process. Use no more "
        "than four Web Search calls, reserve output for the final object, and return only JSON.\n\n"
        f"Output example: {json.dumps(output_example, ensure_ascii=False)}\n\n"
        f"University: {request.university}\n"
        f"Programme: {request.program_name}\n"
        f"Official programme URL reference: {request.official_program_url or 'unknown'}\n"
        f"Intended entry year: {request.intended_entry_year}\n"
        f"Intended entry term: {request.intended_entry_term}"
    )
    timeline = await call_deepseek_web_search(
        prompt,
        ApplicationTimeline,
        schema_name="application_timeline",
        max_output_tokens=3200,
        max_search_uses=4,
    )
    return normalize_application_timeline(timeline)


async def retrieve_application_timeline_cached(
    request: ApplicationTimelineRequest,
    *,
    force_refresh: bool = False,
    cache: ProgrammeCache = PROGRAMME_CACHE,
) -> ApplicationTimeline:
    """Read runtime/seed snapshots before invoking the unchanged live workflow."""
    identity = timeline_cache_identity(request)
    cache_key = programme_cache_key(identity)
    if not force_refresh:
        for source, reader in (
            ("runtime_cache", cache.read_runtime),
            ("seed", cache.read_seed),
        ):
            record = reader("timeline", cache_key)
            if record is None:
                continue
            try:
                timeline = ApplicationTimeline.model_validate(record.payload)
            except ValidationError as error:
                logger.warning(
                    "programme_cache_payload_invalid kind=timeline source=%s key=%s error=%s",
                    source,
                    cache_key,
                    error,
                )
                continue
            logger.info("programme_cache_hit kind=timeline source=%s key=%s", source, cache_key)
            return timeline

    timeline = await retrieve_application_timeline(request)
    if timeline.status != "not_found":
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            cache.write_runtime(
                "timeline",
                cache_key,
                checked_at,
                timeline.model_dump(mode="json"),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            logger.warning(
                "programme_cache_runtime_write_failed kind=timeline key=%s error=%s",
                cache_key,
                error,
            )
    logger.info("programme_cache_result kind=timeline source=live key=%s", cache_key)
    return timeline


@app.post(
    "/target-programs/timeline",
    response_model=ApplicationTimeline,
    tags=["programs"],
)
async def target_program_timeline_endpoint(
    request: ApplicationTimelineRequest,
    force_refresh: bool = Query(default=False),
) -> ApplicationTimeline:
    try:
        return await asyncio.wait_for(
            retrieve_application_timeline_cached(request, force_refresh=force_refresh),
            timeout=TIMELINE_TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=504, detail="申请时间线获取超时，请重试。") from error


def profile_user_evidence(profile: UserProfile) -> List[UserEvidence]:
    """Expose reusable facts already present in the compatible UserProfile schema."""
    now = datetime.now(timezone.utc).isoformat()
    evidence: List[UserEvidence] = []

    def add(
        evidence_type: GapEvidenceType,
        key: str,
        value: Any,
        raw_answer: str,
        availability: EvidenceAvailability = "known",
    ) -> None:
        evidence.append(
            UserEvidence(
                evidence_type=evidence_type,
                key=key,
                value=value,
                raw_answer=raw_answer,
                availability=availability,
                updated_at=now,
            )
        )

    if profile.education.university:
        availability: EvidenceAvailability = (
            "unknown" if profile.education.university == "无法提供" else "known"
        )
        add(
            "education_university",
            "education.university",
            profile.education.university if availability == "known" else None,
            profile.education.university,
            availability,
        )
    if profile.education.major:
        availability = "unknown" if profile.education.major == "无法提供" else "known"
        add(
            "education_major",
            "education.major",
            profile.education.major if availability == "known" else None,
            profile.education.major,
            availability,
        )
    for key, score in (
        ("gpa", profile.education.gpa),
        ("average_score", profile.education.average_score),
    ):
        if score is not None and score.value is not None:
            add(
                "academic_score",
                key,
                {"score": score.value, "scale": score.scale},
                f"{score.value}/{score.scale}" if score.scale else str(score.value),
            )
    if profile.education.courses:
        if profile.education.courses == ["无法提供"]:
            add("courses", "courses", None, "无法提供", "unknown")
        else:
            add(
                "courses",
                "courses",
                profile.education.courses,
                "；".join(profile.education.courses),
            )
    for key, score, status, subscores in (
        (
            "ielts",
            profile.language.IELTS,
            profile.language.IELTS_status,
            profile.language.IELTS_subscores,
        ),
        (
            "toefl",
            profile.language.TOEFL,
            profile.language.TOEFL_status,
            profile.language.TOEFL_subscores,
        ),
        (
            "gre",
            profile.standardized_test.GRE,
            profile.standardized_test.GRE_status,
            {},
        ),
        (
            "gmat",
            profile.standardized_test.GMAT,
            profile.standardized_test.GMAT_status,
            {},
        ),
    ):
        evidence_type: GapEvidenceType = (
            "language_score" if key in {"ielts", "toefl"} else "standardized_score"
        )
        if status == "none":
            add(evidence_type, key, None, "没有正式成绩", "known_negative")
        elif status == "unknown":
            add(evidence_type, key, None, "不确定 / 不记得", "unknown")
        elif score is not None:
            add(
                evidence_type,
                key,
                {
                    "score": score,
                    "scale": None,
                    "subscores": {
                        component: value
                        for component, value in subscores.items()
                        if value is not None
                    },
                },
                str(score),
            )
    material_statuses = (
        ("materials.cv", profile.materials.cv_status),
        ("materials.transcript", profile.materials.transcript_status),
        ("materials.degree_certificate", profile.materials.degree_certificate_status),
        ("materials.personal_statement", profile.materials.motivation_letter_status),
        ("materials.portfolio", profile.materials.portfolio_status),
    )
    for key, status in material_statuses:
        if status is None:
            continue
        if status == "prepared":
            add(
                "material_status",
                key,
                {"value_kind": "boolean", "value": True, "available": True},
                "已准备",
            )
        elif status in {"not_prepared", "not_applicable"}:
            add(
                "material_status",
                key,
                {"value_kind": "boolean", "value": False, "available": False},
                "未准备" if status == "not_prepared" else "不适用",
                "known_negative",
            )
        else:
            add("material_status", key, None, "不确定", "unknown")
    if profile.materials.confirmed_recommenders is not None:
        quantity = profile.materials.confirmed_recommenders
        add(
            "material_quantity",
            "materials.recommendations",
            {"value_kind": "numeric", "value": quantity, "quantity": quantity},
            str(quantity),
        )
    experience = [
        *profile.experience.projects,
        *profile.experience.research,
        *profile.experience.internship,
    ]
    if experience:
        availability = "unknown" if experience == ["无法提供"] else "known"
        add(
            "experience",
            "experience",
            experience if availability == "known" else None,
            "；".join(experience),
            availability,
        )
    return evidence


def scoped_standard_material_owner_key(item: UserEvidence) -> Optional[str]:
    canonical_key = canonical_evidence_key(item.key)
    if not canonical_key.startswith(("material_item.", "material_quantity.")):
        return None
    if not isinstance(item.value, dict):
        return None
    material_type = item.value.get("material_type")
    return {
        "cv": "materials.cv",
        "transcript": "materials.transcript",
        "personal_statement": "materials.personal_statement",
        "portfolio": "materials.portfolio",
        "recommendation_letters": "materials.recommendations",
    }.get(str(material_type))


def merge_reusable_evidence(
    profile: UserProfile,
    user_evidence: List[UserEvidence],
) -> List[UserEvidence]:
    merged: Dict[str, UserEvidence] = {}
    profile_evidence = profile_user_evidence(profile)
    profile_keys = {canonical_evidence_key(item.key) for item in profile_evidence}
    for item in user_evidence:
        scoped_owner_key = scoped_standard_material_owner_key(item)
        if scoped_owner_key and scoped_owner_key in profile_keys:
            logger.info(
                "legacy_standard_profile_evidence_ignored key=%s source=standard_profile",
                canonical_evidence_key(item.key),
            )
            continue
        canonical_key = canonical_evidence_key(item.key)
        canonical_item = item.model_copy(update={"key": canonical_key})
        existing = merged.get(canonical_key)
        if (
            existing
            and existing.availability == "known"
            and canonical_item.availability == "known"
        ):
            canonical_item = canonical_item.model_copy(
                update={
                    "value": merge_evidence_value(existing.value, canonical_item.value)
                }
            )
        merged[canonical_key] = canonical_item
    for item in profile_evidence:
        canonical_key = canonical_evidence_key(item.key)
        merged[canonical_key] = item.model_copy(update={"key": canonical_key})
    return list(merged.values())


EVIDENCE_KEY_CANONICAL_ALIASES = {
    "language.ielts": "ielts",
    "english.ielts": "ielts",
    "materials.ielts": "ielts",
    "language.toefl": "toefl",
    "english.toefl": "toefl",
    "materials.toefl": "toefl",
    "personal_statement": "materials.personal_statement",
    "statement_of_purpose": "materials.personal_statement",
    "materials.statement_of_purpose": "materials.personal_statement",
    "materials.sop": "materials.personal_statement",
    "materials.motivation_letter": "materials.personal_statement",
    "motivation_letter": "materials.personal_statement",
    "cv": "materials.cv",
    "transcript": "materials.transcript",
    "portfolio": "materials.portfolio",
    "degree_certificate": "materials.degree_certificate",
    "recommendations": "materials.recommendations",
    "recommendation_letters": "materials.recommendations",
    "materials.recommendation_letters": "materials.recommendations",
    "references": "materials.recommendations",
    "materials.references": "materials.recommendations",
}


STANDARD_MATERIAL_KEYS: Dict[str, tuple[StandardMaterialType, str]] = {
    "materials.cv": ("cv", "CV / 简历"),
    "materials.transcript": ("transcript", "成绩单"),
    "materials.personal_statement": ("personal_statement", "SOP / 动机信"),
    "materials.portfolio": ("portfolio", "作品集"),
    "materials.degree_certificate": ("degree_certificate", "学位证明"),
    "materials.identification": ("identification", "身份证明"),
    "materials.recommendations": ("recommendation_letters", "推荐信"),
}


def canonical_evidence_key(key: str) -> str:
    normalized = key.strip().casefold()
    return EVIDENCE_KEY_CANONICAL_ALIASES.get(normalized, normalized)


def standard_material_definition(
    key: str,
) -> Optional[tuple[StandardMaterialType, str]]:
    return STANDARD_MATERIAL_KEYS.get(canonical_evidence_key(key))


def material_policy_item_id(requirement_id: str, material_type: str) -> str:
    digest = hashlib.sha256(
        f"{requirement_id}\n{material_type}".encode("utf-8")
    ).hexdigest()[:16]
    return f"material-{digest}"


def material_policy_evidence_key(item_id: str, *, quantity: bool = False) -> str:
    prefix = "material_quantity" if quantity else "material_item"
    return f"{prefix}.{item_id}"


def other_policy_item_id(requirement_id: str, label: str) -> str:
    normalized_label = " ".join(label.casefold().split())
    digest = hashlib.sha256(
        f"{requirement_id}\n{normalized_label}".encode("utf-8")
    ).hexdigest()[:16]
    return f"other-{digest}"


def other_policy_evidence_key(item_id: str) -> str:
    return f"other_item.{item_id}"


def normalize_other_descriptors(
    requirement_id: str,
    requirement_text: str,
    descriptors: List[GapOtherEvidenceDescriptor],
    evidence_needs: List[GapEvidenceNeed],
) -> List[GapOtherItem]:
    needs_by_key = {
        canonical_evidence_key(need.key): need for need in evidence_needs
    }
    requirement_folded = " ".join(requirement_text.casefold().split())
    normalized: List[GapOtherItem] = []
    used_source_keys: Set[str] = set()
    for descriptor in descriptors:
        source_key = canonical_evidence_key(descriptor.source_evidence_key)
        source_need = needs_by_key.get(source_key)
        if source_need is None or source_key in used_source_keys:
            logger.warning(
                "other_descriptor_invalid_source requirement_id=%s key=%s dropped=true",
                requirement_id,
                source_key,
            )
            continue
        if source_need.evidence_type not in {"generic", "material_status", "material_quantity"}:
            continue
        options = list(descriptor.options)
        if descriptor.value_kind in {"single_select", "multi_select"}:
            if len(options) < 2 or any(
                " ".join(option.casefold().split()) not in requirement_folded
                for option in options
            ):
                logger.warning(
                    "other_descriptor_unsupported_options requirement_id=%s key=%s dropped=true",
                    requirement_id,
                    source_key,
                )
                continue
            if descriptor.value_kind == "multi_select" and not re.search(
                r"\b(?:select|choose)\s+(?:all|any|one or more|multiple)\b|"
                r"\bmultiple\s+(?:options?|selections?)\b|可多选|选择多个|选择所有",
                requirement_text,
                re.IGNORECASE,
            ):
                logger.warning(
                    "other_descriptor_multi_select_not_explicit requirement_id=%s key=%s dropped=true",
                    requirement_id,
                    source_key,
                )
                continue
        elif options:
            options = []
        item_id = other_policy_item_id(requirement_id, descriptor.label)
        normalized.append(
            GapOtherItem(
                **descriptor.model_dump(exclude={"options", "source_evidence_key"}),
                source_evidence_key=source_key,
                options=options,
                item_id=item_id,
                evidence_key=other_policy_evidence_key(item_id),
            )
        )
        used_source_keys.add(source_key)
    return normalized


def scope_legacy_material_evidence(
    requirements: List["GapPlannedRequirement"],
    evidence_by_key: Dict[str, UserEvidence],
) -> None:
    needs = [
        (requirement, need)
        for requirement in requirements
        for need in requirement.evidence_needs
        if need.material_type is not None and need.item_id
    ]
    owner_count: Dict[StandardMaterialType, int] = {}
    for _, need in needs:
        owner_count[need.material_type] = owner_count.get(need.material_type, 0) + 1
    legacy_key_by_type = {
        material_type: key
        for key, (material_type, _) in STANDARD_MATERIAL_KEYS.items()
    }
    for requirement, need in needs:
        if need.key in evidence_by_key:
            continue
        legacy_key = legacy_key_by_type.get(need.material_type)
        legacy = evidence_by_key.get(legacy_key or "")
        if legacy and (
            owner_count.get(need.material_type) == 1
            or requirement.requirement_id in legacy.source_requirement_ids
        ):
            evidence_by_key[need.key] = legacy.model_copy(update={"key": need.key})


def canonical_evidence_value_kind(
    key: str,
    evidence_type: Any,
) -> Optional[EvidenceValueKind]:
    canonical_key = canonical_evidence_key(key)
    if canonical_key.startswith(
        (
            "prerequisite_course:",
            "course_category_response:",
            "course_requirement.",
            "programme_course_response:",
        )
    ):
        return "boolean"
    key_leaf = canonical_key.rsplit(".", 1)[-1]
    if key_leaf == "degree_classification":
        return "categorical"
    if key_leaf in {"gpa", "average_score"}:
        return "numeric"
    by_type: Dict[str, EvidenceValueKind] = {
        "education_university": "text",
        "education_major": "text",
        "academic_score": "numeric",
        "language_score": "numeric",
        "standardized_score": "numeric",
        "courses": "text",
        "material_status": "boolean",
        "material_quantity": "numeric",
        "experience": "text",
    }
    return by_type.get(str(evidence_type))


def validated_evidence_value_kind(
    key: str,
    evidence_type: Any,
    model_value_kind: EvidenceValueKind,
) -> EvidenceValueKind:
    canonical = canonical_evidence_value_kind(key, evidence_type)
    if canonical and canonical != model_value_kind:
        logger.warning(
            "gap_evidence_value_kind_conflict key=%s model=%s canonical=%s",
            canonical_evidence_key(key),
            model_value_kind,
            canonical,
        )
    return canonical or model_value_kind


def canonical_language_proof_kind(key: str) -> Optional[LanguageProofKind]:
    canonical_key = canonical_evidence_key(key)
    if canonical_key in {"ielts", "toefl"}:
        return "scored_test"
    if canonical_key == "education.language_medium":
        return "medium_of_instruction"
    return None


def validated_language_proof_kind(
    key: str,
    model_proof_kind: Optional[LanguageProofKind],
) -> Optional[LanguageProofKind]:
    canonical = canonical_language_proof_kind(key)
    if canonical and model_proof_kind and canonical != model_proof_kind:
        logger.warning(
            "gap_evidence_proof_kind_conflict key=%s model=%s canonical=%s",
            canonical_evidence_key(key),
            model_proof_kind,
            canonical,
        )
    return canonical or model_proof_kind


INFORMATIONAL_APPLICATION_PATTERNS = (
    r"\bgraduate application form\b",
    r"\bapplication fee\b",
    r"\bapplication portal\b",
    r"\bhow to apply\b",
    r"\bsubmit(?:ted)?\s+(?:an?\s+)?application\s+(?:through|via)\b",
    r"\bapply\s+(?:through|via)\b",
    r"\b(?:materials?|documents?)\b.*\b(?:cannot|may not|must not)\s+be\s+"
    r"(?:updated|changed|replaced)\b.*\bdeadline\b",
    r"\bfull information\b.*\b(?:page|link|website)\b",
)
INFORMATIONAL_PROGRAMME_PATTERNS = (
    r"\bfull[- ]time\b",
    r"\bpart[- ]time\b",
    r"\battendance\s+(?:in|at|on)\b",
    r"\bresidence requirement\b",
    r"\bstudy mode\b",
    r"\bprogramme location\b",
    r"\bprogram location\b",
)
INFORMATIONAL_TIMELINE_PATTERNS = (
    r"\bapplication deadline\b",
    r"\bapplications? open\b",
    r"\bapplications?\s+closes?\b",
    r"\badmission rounds?\b",
    r"\bapplication rounds?\b",
)
SUPPORTING_MATERIAL_INVENTORY = (
    (
        "transcript",
        r"\b(?:official\s+|academic\s+)*transcripts?\b",
        "Official academic transcript(s) are required as supporting documents.",
        "需要提交正式成绩单作为申请材料。",
    ),
    (
        "degree_certificate",
        r"\b(?:degree|graduation) certificates?\b|\bdiplomas?\b",
        "A degree certificate or diploma is required as a supporting document.",
        "需要提交学位证明作为申请材料。",
    ),
    (
        "cv",
        r"\b(?:cv|curriculum vitae|r[eé]sum[eé])\b",
        "A current CV or résumé is required as a supporting document.",
        "需要提交最新个人简历作为申请材料。",
    ),
    (
        "recommendations",
        r"\b(?:references?|reference letters?|recommendation letters?|letters? of recommendation)\b",
        "Reference or recommendation letter(s) are required as supporting documents.",
        "需要提交推荐信作为申请材料。",
    ),
    (
        "personal_statement",
        r"\b(?:personal statement|statement of purpose|motivation letter)\b",
        "A personal statement or statement of purpose is required as a supporting document.",
        "需要提交个人陈述作为申请材料。",
    ),
    (
        "portfolio",
        r"\b(?:portfolio|work sample)\b",
        "A portfolio or work sample is required as a supporting document.",
        "需要提交作品集或作品样本作为申请材料。",
    ),
    (
        "identification",
        r"\b(?:identification document|identity document|passport copy)\b",
        "An identification document is required as a supporting document.",
        "需要提交身份证明作为申请材料。",
    ),
    (
        "programme_specific_form",
        r"\bprogramme[- ]specific\s+(?:form|sheet|questionnaire)\b",
        "A programme-specific form, sheet, or questionnaire is required.",
        "需要提交项目专用表格、信息表或问卷。",
    ),
)


def informational_requirement_kind(category: RequirementCategory, text: str) -> Optional[str]:
    lowered = text.casefold()
    if any(re.search(pattern, lowered) for pattern in INFORMATIONAL_TIMELINE_PATTERNS):
        return "timeline"
    if category == "other" and any(
        re.search(pattern, lowered) for pattern in INFORMATIONAL_PROGRAMME_PATTERNS
    ):
        return "programme_information"
    if any(re.search(pattern, lowered) for pattern in INFORMATIONAL_APPLICATION_PATTERNS):
        return "application_process"
    if category == "other" and re.search(
        r"\b(?:see|visit|available on|linked)\b.*\b(?:page|website|link)\b",
        lowered,
    ):
        return "application_process"
    return None


CORE_REQUIREMENT_PATTERNS = (
    r"\b(?:is|are)\s+(?:explicitly\s+)?required\b",
    r"\b(?:requires?|requiring)\b",
    r"\bmust\s+(?:have|hold|achieve|obtain|complete|include|provide|submit|upload|supply)\b",
)


def requirement_has_explicit_matchable_core(
    category: RequirementCategory,
    text: str,
) -> bool:
    if category == "other":
        return False
    normalized = " ".join(text.split())
    return any(
        re.search(pattern, normalized, re.IGNORECASE)
        for pattern in CORE_REQUIREMENT_PATTERNS
    )


def supporting_materials_in_requirement(text: str) -> List[tuple[str, str, str]]:
    return [
        (material_key, requirement, requirement_zh)
        for material_key, pattern, requirement, requirement_zh in SUPPORTING_MATERIAL_INVENTORY
        if re.search(pattern, text, re.IGNORECASE)
    ]


SPECIAL_INTERNAL_ROUTE_PATTERNS = (
    r"\b(?:available|open|offered|reserved|limited|restricted)\s+"
    r"(?:exclusively\s+|only\s+)?(?:to|for)\s+(?:current|currently\s+enrolled)\s+"
    r"[^.;:()]{0,120}\b(?:undergraduates?|seniors?|students?)\b",
    r"\bonly\s+(?:current|currently\s+enrolled)\s+[^.;:()]{0,120}"
    r"\b(?:undergraduates?|seniors?|students?)\b",
    r"\b(?:internal[- ]only|internal\s+progression\s+applicants?|"
    r"internal\s+applicants?\s+only)\b",
    r"仅(?:面向|适用于|开放给).{0,80}(?:本校|当前在读|内部升学).{0,40}"
    r"(?:本科生|高年级学生|申请人)",
)


def requirement_route_scope(requirement_text: str) -> ApplicationRouteScope:
    normalized = " ".join(requirement_text.split())
    return (
        "special_internal"
        if any(
            re.search(pattern, normalized, re.IGNORECASE)
            for pattern in SPECIAL_INTERNAL_ROUTE_PATTERNS
        )
        else "standard"
    )


NAMED_APPLICATION_ROUTE_PATTERN = re.compile(
    r"\b(?:[Tt]he\s+)?"
    r"([A-Z][A-Za-z0-9&+./'-]*(?:\s+[A-Z][A-Za-z0-9&+./'-]*){0,6})\s+"
    r"([Pp]athway|[Pp]rogramme|[Pp]rogram|[Rr]oute)\b"
)
ROUTE_IDENTITY_WRAPPERS = {"pathway", "programme", "program", "route"}


def named_application_route_identities(requirement_text: str) -> Set[str]:
    identities: Set[str] = set()
    for match in NAMED_APPLICATION_ROUTE_PATTERN.finditer(requirement_text):
        words = [*match.group(1).split(), match.group(2)]
        while words and words[-1].casefold() in ROUTE_IDENTITY_WRAPPERS:
            words.pop()
        identity = " ".join(words).casefold()
        if identity:
            identities.add(identity)
    return identities


def formal_gap_requirements(
    review: TargetProgramRequirementsReview,
) -> List[Dict[str, Any]]:
    formal = []
    source_requirements = [
        (category, index, requirement)
        for category in review.categories
        for index, requirement in enumerate(category.requirements)
        if requirement.verification_status
        in {"official_verified", "model_memory_unverified", "user_supplied"}
    ]
    special_internal_route_identities = {
        route_identity
        for _, _, requirement in source_requirements
        if requirement_route_scope(requirement.requirement) == "special_internal"
        for route_identity in named_application_route_identities(requirement.requirement)
    }
    has_language_requirement = any(
        category.category == "language" and category.requirements
        for category in review.categories
    )
    for category in review.categories:
        for index, requirement in enumerate(category.requirements):
            if requirement.verification_status not in {
                "official_verified",
                "model_memory_unverified",
                "user_supplied",
            }:
                continue
            if requirement.applicability_stage != "pre_admission":
                continue
            direct_route_scope = requirement_route_scope(requirement.requirement)
            route_identities = named_application_route_identities(
                requirement.requirement
            )
            inherits_named_route_scope = bool(
                direct_route_scope == "standard"
                and route_identities & special_internal_route_identities
            )
            route_scope: ApplicationRouteScope = (
                "special_internal"
                if direct_route_scope == "special_internal"
                or inherits_named_route_scope
                else "standard"
            )
            route_scope_source = (
                "named_route"
                if inherits_named_route_scope
                else "current_requirement"
            )
            base = {
                "category": category.category,
                "requirement": requirement.requirement,
                "requirement_zh": requirement.requirement_zh,
                "importance": requirement.importance,
                "requirement_verification_status": requirement.verification_status,
                "source_url": requirement.source_url,
                "source_cycle": requirement.source_cycle,
                "temporal_applicability": requirement.temporal_applicability,
                "temporal_note": requirement.temporal_note,
                "applicability_stage": requirement.applicability_stage,
                "route_scope": route_scope,
                "excluded_reason": (
                    "unsupported_special_internal_route"
                    if route_scope == "special_internal"
                    else None
                ),
                "route_scope_source": route_scope_source,
            }
            requirement_id = f"{category.category}:{index}"
            informational_kind = informational_requirement_kind(
                category.category,
                requirement.requirement,
            )
            has_matchable_core = requirement_has_explicit_matchable_core(
                category.category,
                requirement.requirement,
            )
            supporting_materials = supporting_materials_in_requirement(
                requirement.requirement
            )
            if informational_kind and supporting_materials:
                parent_has_conditional_scope = requirement_has_explicit_conditional_scope(
                    requirement.requirement
                )
                for material_key, material_text, material_text_zh in supporting_materials:
                    formal.append(
                        {
                            **base,
                            "requirement_id": f"{requirement_id}:{material_key}",
                            "category": "materials",
                            "requirement": material_text,
                            "requirement_zh": material_text_zh,
                            "gap_eligibility": "matchable",
                            "parent_requirement_id": requirement_id,
                            "parent_requirement_text": requirement.requirement,
                            "parent_scope_requirement_id": f"{requirement_id}:process",
                            "parent_has_explicit_conditional_scope": parent_has_conditional_scope,
                            "inherits_parent_applicability": parent_has_conditional_scope,
                            "route_scope_source": "parent",
                        }
                    )
                formal.append(
                    {
                        **base,
                        "requirement_id": f"{requirement_id}:process",
                        "gap_eligibility": informational_kind,
                        "parent_requirement_id": requirement_id,
                        "parent_requirement_text": requirement.requirement,
                        "parent_has_explicit_conditional_scope": parent_has_conditional_scope,
                        "inherits_parent_applicability": False,
                    }
                )
                continue
            if has_matchable_core:
                informational_kind = None
            duplicate_language_material = bool(
                has_language_requirement
                and category.category == "materials"
                and re.search(
                    r"\b(?:evidence|proof) of english(?: language)? proficiency\b",
                    requirement.requirement,
                    re.IGNORECASE,
                )
            )
            formal.append(
                {
                    **base,
                    "requirement_id": requirement_id,
                    "gap_eligibility": (
                        "duplicate_language_reference"
                        if duplicate_language_material
                        else informational_kind or "matchable"
                    ),
                }
            )
    return formal


def requirement_is_temporally_matchable(
    temporal_applicability: RequirementTemporalApplicability,
) -> bool:
    return temporal_applicability in {"target_cycle_confirmed", "undated"}


def requirement_allows_evidence_collection(
    temporal_applicability: RequirementTemporalApplicability,
) -> bool:
    return temporal_applicability != "not_yet_published"


def temporal_gap_explanation(
    temporal_applicability: RequirementTemporalApplicability,
    source_cycle: Optional[str],
    temporal_note: Optional[str],
) -> tuple[str, str]:
    if temporal_applicability == "previous_cycle":
        cycle = f"（来源周期：{source_cycle}）" if source_cycle else ""
        return (
            "仅作上一周期参考",
            temporal_note
            or f"该要求来自其他申请周期{cycle}，尚未确认适用于目标申请周期。",
        )
    if temporal_applicability == "not_yet_published":
        return (
            "目标周期要求尚未发布",
            temporal_note or "官方尚未发布目标申请周期的相关要求，不执行硬性匹配。",
        )
    return (
        "目标周期适用性待确认",
        temporal_note or "当前来源的周期适用性无法确定，不执行硬性匹配。",
    )


def required_fields_for_evidence_need(
    need: GapEvidenceNeed,
    constraint: GapDeterministicConstraint,
) -> List[str]:
    matching_options = [
        option
        for option in constraint.options
        if canonical_evidence_key(option.key) == canonical_evidence_key(need.key)
    ]
    if (
        need.evidence_type == "standardized_score"
        and canonical_evidence_key(need.key) == "gre"
    ):
        components = list(
            dict.fromkeys(
                option.component
                for option in matching_options
                if option.component is not None
            )
        )
        return components or ["verbal", "quantitative", "analytical_writing"]
    if need.evidence_type == "academic_score":
        academic_key = canonical_evidence_key(need.key).rsplit(".", 1)[-1]
        academic_value_kind = {
            "degree_classification": "categorical",
        }.get(academic_key, "numeric")
        if academic_value_kind == "categorical" or (
            matching_options
            and not any(option.kind == "score" for option in matching_options)
        ):
            return ["description"]
        if academic_key in {"gpa", "average_score"}:
            return ["score", "scale"]
    if need.evidence_type in {"language_score", "standardized_score", "academic_score"}:
        fields = ["score"]
        if need.evidence_type == "language_score" and any(
            option.component_minimum is not None for option in matching_options
        ):
            fields.extend(["listening", "reading", "writing", "speaking"])
        return fields
    if need.evidence_type == "material_quantity":
        return ["quantity"]
    if need.evidence_type == "material_status":
        return ["status"]
    if need.evidence_type == "courses" and any(
        option.kind == "course_credit" for option in matching_options
    ):
        return ["quantity"]
    if need.evidence_type == "experience":
        return ["has_experience", "experience_types", "duration", "unit"]
    return ["description"]


def normalize_course_requirements(
    requirement_id: str,
    items: List[GapCourseRequirement],
    evidence_needs: List[GapEvidenceNeed],
) -> List[GapCourseRequirement]:
    course_keys = {
        canonical_evidence_key(need.key)
        for need in evidence_needs
        if need.evidence_type == "courses"
    }
    normalized = []
    seen_courses = set()
    for item in items:
        evidence_key = canonical_evidence_key(item.evidence_key)
        if evidence_key not in course_keys:
            logger.warning(
                "course_requirement_invalid_evidence_key requirement_id=%s key=%s dropped=true",
                requirement_id,
                evidence_key,
            )
            continue
        dedup_key = " ".join(item.course_name.casefold().split())
        if dedup_key in seen_courses:
            logger.warning(
                "course_requirement_duplicate requirement_id=%s course=%s dropped=true",
                requirement_id,
                item.course_name,
            )
            continue
        seen_courses.add(dedup_key)
        prerequisite_kind = item.prerequisite_kind
        if prerequisite_kind is None:
            if evidence_key.startswith("course_category_response:"):
                prerequisite_kind = "course_category"
            elif evidence_key.startswith("prerequisite_course:"):
                prerequisite_kind = "concrete_course"
        normalized.append(
            item.model_copy(
                update={
                    "item_id": course_requirement_item_id(
                        requirement_id, item.course_name
                    ),
                    "evidence_key": evidence_key,
                    "prerequisite_kind": prerequisite_kind,
                    "canonical_label": item.canonical_label or item.course_name,
                }
            )
        )
    return normalized


def authoritative_gap_course_requirements(
    target_program: TargetProgram,
    requirement_id: str,
    groups: List[AuthoritativePrerequisiteGroup],
) -> List[GapCourseRequirement]:
    normalized: List[GapCourseRequirement] = []
    seen_item_ids: Set[str] = set()
    for group in groups:
        if group.requirement_id != requirement_id:
            continue
        for item in group.items:
            source_identity = item.canonical_label or item.category_label or item.display_label
            expected_item_id = authoritative_prerequisite_item_id(
                requirement_id,
                item.prerequisite_kind,
                source_identity,
            )
            expected_key = programme_course_evidence_key(
                target_program,
                requirement_id,
                expected_item_id,
            )
            if item.item_id != expected_item_id or canonical_evidence_key(
                item.evidence_key
            ) != expected_key:
                logger.warning(
                    "authoritative_course_item_invalid requirement_id=%s item_id=%s dropped=true",
                    requirement_id,
                    item.item_id,
                )
                continue
            if item.item_id in seen_item_ids:
                continue
            seen_item_ids.add(item.item_id)
            normalized.append(
                GapCourseRequirement(
                    item_id=item.item_id,
                    evidence_key=expected_key,
                    course_name=item.display_label,
                    canonical_label=source_identity,
                    prerequisite_kind=item.prerequisite_kind,
                    authoritative=True,
                    group_id=group.group_id,
                    group_relation=group.relation,
                )
            )
    return normalized


def authoritative_gap_course_credit_items(
    target_program: TargetProgram,
    requirement_id: str,
    items: List[AuthoritativeCourseCreditItem],
) -> List[AuthoritativeCourseCreditItem]:
    normalized: List[AuthoritativeCourseCreditItem] = []
    seen_item_ids: Set[str] = set()
    for item in items:
        if item.requirement_id != requirement_id:
            continue
        expected_item_id = authoritative_course_credit_item_id(
            requirement_id,
            item.required_quantity,
            item.unit,
        )
        expected_key = programme_course_credit_evidence_key(
            target_program,
            requirement_id,
            expected_item_id,
        )
        if item.item_id != expected_item_id or canonical_evidence_key(
            item.evidence_key
        ) != expected_key:
            logger.warning(
                "authoritative_course_credit_invalid requirement_id=%s item_id=%s dropped=true",
                requirement_id,
                item.item_id,
            )
            continue
        if item.item_id in seen_item_ids:
            continue
        seen_item_ids.add(item.item_id)
        normalized.append(item.model_copy(update={"evidence_key": expected_key}))
    return normalized


def course_requirement_item_id(requirement_id: str, course_name: str) -> str:
    normalized_name = " ".join(course_name.casefold().split())
    digest = hashlib.sha256(
        f"{requirement_id}\n{normalized_name}".encode("utf-8")
    ).hexdigest()[:16]
    return f"course-{digest}"


def course_requirement_evidence_key(item_id: str) -> str:
    return f"course_requirement.{item_id}"


def course_requirement_credit_evidence_key(item_id: str) -> str:
    return f"course_requirement_credit.{item_id}"


def normalize_conditional_metadata(
    requirement_id: str,
    requirement_text: str,
    metadata: GapConditionalMetadata,
    evidence_needs: List[GapEvidenceNeed],
) -> GapConditionalMetadata:
    if not metadata.is_conditional:
        if (
            metadata.condition_text
            or metadata.controlling_evidence_keys
            or metadata.predicates
            or metadata.predicate_relation != "all"
        ):
            logger.warning(
                "conditional_metadata_unconditional_payload requirement_id=%s cleared=true",
                requirement_id,
            )
        return GapConditionalMetadata()
    if not metadata.condition_text:
        logger.warning(
            "conditional_metadata_missing_condition_text requirement_id=%s normalized=unconditional",
            requirement_id,
        )
        return GapConditionalMetadata()
    if not requirement_has_explicit_conditional_scope(requirement_text):
        logger.warning(
            "conditional_metadata_scope_not_explicit requirement_id=%s normalized=unconditional",
            requirement_id,
        )
        return GapConditionalMetadata()
    owned_keys = {
        canonical_evidence_key(need.key)
        for need in evidence_needs
    }
    controlling_keys = []
    for raw_key in metadata.controlling_evidence_keys:
        key = canonical_evidence_key(raw_key)
        if key not in owned_keys:
            logger.warning(
                "conditional_metadata_invalid_evidence_key requirement_id=%s key=%s dropped=true",
                requirement_id,
                key,
            )
            continue
        if key not in controlling_keys:
            controlling_keys.append(key)
    predicates = []
    for predicate in metadata.predicates:
        key = canonical_evidence_key(predicate.evidence_key)
        if key not in controlling_keys:
            logger.warning(
                "conditional_predicate_invalid_evidence_key requirement_id=%s key=%s dropped=true",
                requirement_id,
                key,
            )
            continue
        normalized_predicate = predicate.model_copy(update={"evidence_key": key})
        if normalized_predicate not in predicates:
            predicates.append(normalized_predicate)
    return metadata.model_copy(
        update={
            "controlling_evidence_keys": controlling_keys,
            "predicates": predicates,
        }
    )


def requirement_has_explicit_conditional_scope(requirement_text: str) -> bool:
    return bool(
        re.search(
            r"\bif\b|\bwhere applicable\b|\bonly\s+(?:for|if|when|current)\b|"
            r"\bapplicants?\s+(?:from|with|who|choosing|selecting)\b|"
            r"\bfor\s+(?:the\s+)?[^.;:]{0,100}\b(?:pathway|track|speciali[sz]ation|stream|route)\b|"
            r"\bwhen\s+[^.;:]{1,100}\b(?:applies|required|selected|chosen)\b|"
            r"如适用|仅适用于|只适用于|如果|若|选择.+(?:方向|路径|项目)",
            requirement_text,
            re.IGNORECASE,
        )
    )


def normalized_conditional_value(value: str) -> str:
    return " ".join(value.casefold().split())


def conditional_predicate_truth(
    predicate: GapConditionalPredicate,
    item: Optional[UserEvidence],
) -> Optional[bool]:
    if item is None or item.availability == "unknown":
        return None
    if item.availability == "known_negative":
        return False
    value = item.value
    if isinstance(value, dict):
        value = value.get("value", value.get("selected_values", value.get("description")))
    if not isinstance(value, str) or not value.strip():
        return None
    normalized_value = normalized_conditional_value(value)
    normalized_expected = {
        normalized_conditional_value(expected)
        for expected in predicate.expected_values
    }
    if predicate.operator == "equals":
        return normalized_value == next(iter(normalized_expected))
    if predicate.operator == "in":
        return normalized_value in normalized_expected
    return None


def resolve_conditional_state(
    requirement: GapPlannedRequirement,
    reusable_by_key: Dict[str, UserEvidence],
) -> ConditionalApplicabilityState:
    metadata = requirement.conditional
    if not metadata.is_conditional:
        return "not_conditional"
    if not metadata.controlling_evidence_keys or not metadata.predicates:
        return "pending"
    truths = [
        conditional_predicate_truth(
            predicate,
            reusable_by_key.get(canonical_evidence_key(predicate.evidence_key)),
        )
        for predicate in metadata.predicates
    ]
    if metadata.predicate_relation == "all":
        if any(value is None for value in truths):
            return "pending"
        return "active" if all(truths) else "inactive"
    if any(value is True for value in truths):
        return "active"
    if all(value is False for value in truths):
        return "inactive"
    return "pending"


def conditional_question_policy_view(
    requirements: List[GapPlannedRequirement],
) -> List[GapPlannedRequirement]:
    visible: List[GapPlannedRequirement] = []
    for requirement in requirements:
        if requirement.conditional_state in {"not_conditional", "active"}:
            visible.append(requirement)
            continue
        if requirement.conditional_state == "inactive":
            continue
        controlling_keys = {
            canonical_evidence_key(key)
            for key in requirement.conditional.controlling_evidence_keys
        }
        if not controlling_keys:
            continue
        controlling_needs = [
            need
            for need in requirement.evidence_needs
            if need.key in controlling_keys
        ]
        if not controlling_needs:
            continue
        visible.append(
            requirement.model_copy(
                update={
                    "evidence_needs": controlling_needs,
                    "constraint": requirement.constraint.model_copy(
                        update={
                            "options": [
                                option
                                for option in requirement.constraint.options
                                if canonical_evidence_key(option.key) in controlling_keys
                            ]
                        }
                    ),
                    "course_requirements": [
                        item
                        for item in requirement.course_requirements
                        if gap_course_item_evidence_key(item)
                        in controlling_keys
                        or course_requirement_credit_evidence_key(item.item_id)
                        in controlling_keys
                    ],
                    "other_items": [
                        item
                        for item in requirement.other_items
                        if item.evidence_key in controlling_keys
                    ],
                }
            )
        )
    return visible


def friendly_evidence_name(
    key: str,
    need: Optional[GapEvidenceNeed] = None,
) -> str:
    canonical_key = canonical_evidence_key(key)
    suffix = canonical_key.rsplit(".", 1)[-1]
    labels = {
        "degree_classification": "学位等级",
        "gpa": "GPA",
        "average_score": "平均分",
        "ielts": "IELTS 成绩",
        "toefl": "TOEFL 成绩",
        "university": "本科院校",
        "major": "本科专业",
        "experience": "相关经历",
    }
    if suffix in labels:
        return labels[suffix]
    if need and need.label.strip():
        label = need.label.strip()
        if label.casefold() != canonical_key and not re.fullmatch(
            r"[a-z0-9_.-]+",
            label.casefold(),
        ):
            return label
    return "相关信息"


def safe_owned_question_prompt(needs: List[GapEvidenceNeed]) -> str:
    names = list(
        dict.fromkeys(friendly_evidence_name(need.key, need) for need in needs)
    )
    if names == ["本科院校"]:
        return "你的本科院校是什么？"
    if names == ["本科专业"]:
        return "你的本科专业是什么？"
    relation = needs[0].group_relation if needs else "all"
    if len(names) == 1:
        return f"请提供你的{names[0]}。"
    if relation == "any":
        return f"请提供你可用的{'、'.join(names)}信息。"
    return f"请补充以下信息：{'、'.join(names)}。"


def invalid_schema_fallback_prompt(
    evidence_keys: List[str],
    needs_by_key: Optional[Dict[str, GapEvidenceNeed]],
) -> str:
    names = list(
        dict.fromkeys(
            friendly_evidence_name(
                key,
                needs_by_key.get(key) if needs_by_key else None,
            )
            for key in evidence_keys
        )
    )
    if len(names) == 1:
        return f"请提供你的{names[0]}。"
    return f"请补充以下信息：{'、'.join(names)}。"


def question_schema_snapshot(question: GapPlannerQuestion) -> Dict[str, Any]:
    return {
        "question_id": question.question_id,
        "requirement_id": question.requirement_id,
        "prompt": question.prompt or question.question,
        "expected_evidence_keys": list(question.expected_evidence_keys),
        "control_type": question.control_type,
        "options": [option.model_dump(mode="json") for option in question.options],
        "fields": [field.model_dump(mode="json") for field in question.fields],
        "validation": question.validation.model_dump(mode="json"),
    }


def log_question_generation_diagnostics(
    event: str,
    diagnostics: GapQuestionGenerationDiagnostics,
) -> None:
    logger.warning(
        "question_generation_diagnostics event=%s data=%s",
        event,
        json.dumps(diagnostics.model_dump(mode="json"), ensure_ascii=False),
    )


def invalid_structured_question_schema(
    question: GapPlannerQuestion,
    evidence_keys: List[str],
    *,
    evidence_group: Optional[str],
    group_relation: Literal["all", "any"],
    error_code: str,
    failure_stage: QuestionGenerationFailureStage,
) -> GapPlannerQuestion:
    existing = question.generation_diagnostics
    base = existing or GapQuestionGenerationDiagnostics()
    diagnostic_update: Dict[str, Any] = {
        "requirement_id": question.requirement_id,
        "allowed_evidence_keys": list(evidence_keys),
        "group_relation": group_relation,
    }
    if failure_stage == "repair_schema_invalid":
        diagnostic_update.update(
            {
                "repair_schema": question_schema_snapshot(question),
                "repair_failure_stage": failure_stage,
                "repair_validator_error": error_code,
            }
        )
    else:
        diagnostic_update.update(
            {
                "initial_schema": (
                    base.initial_schema
                    if base.initial_schema is not None
                    else question_schema_snapshot(question)
                ),
                "initial_failure_stage": base.initial_failure_stage or failure_stage,
                "initial_validator_error": base.initial_validator_error or error_code,
            }
        )
    diagnostics = base.model_copy(update=diagnostic_update)
    logger.warning(
        "gap_question_schema_invalid question_id=%s requirement_id=%s stage=%s error_code=%s",
        question.question_id,
        question.requirement_id,
        failure_stage,
        error_code,
    )
    log_question_generation_diagnostics(
        "repair_invalid" if failure_stage == "repair_schema_invalid" else "initial_invalid",
        diagnostics,
    )
    return question.model_copy(
        update={
            "evidence_keys": list(evidence_keys),
            "expected_evidence_keys": list(evidence_keys),
            "allowed_evidence_keys": list(evidence_keys),
            "evidence_group": evidence_group,
            "group_relation": group_relation,
            "schema_status": "invalid",
            "schema_error_code": error_code,
            "generation_diagnostics": diagnostics,
        }
    )


def fallback_question_schema(
    question: GapPlannerQuestion,
    evidence_keys: List[str],
    *,
    evidence_group: Optional[str] = None,
    error_code: Optional[str] = None,
    needs_by_key: Optional[Dict[str, GapEvidenceNeed]] = None,
) -> GapPlannerQuestion:
    if error_code:
        logger.warning(
            "gap_question_schema_invalid question_id=%s error_code=%s fallback=text_fallback",
            question.question_id,
            error_code,
        )
    prompt = (
        invalid_schema_fallback_prompt(evidence_keys, needs_by_key)
        if error_code
        else question.prompt or question.question
    )
    group_relations = {
        needs_by_key[key].group_relation
        for key in evidence_keys
        if needs_by_key and key in needs_by_key
    }
    group_relation = (
        group_relations.pop() if len(group_relations) == 1 else question.group_relation
    )
    return question.model_copy(
        update={
            "question": prompt,
            "prompt": prompt,
            "evidence_keys": evidence_keys,
            "expected_evidence_keys": evidence_keys,
            "allowed_evidence_keys": evidence_keys,
            "evidence_group": evidence_group,
            "group_relation": group_relation,
            "control_type": "text_fallback",
            "options": [],
            "fields": [],
            "validation": GapQuestionValidation(required=True),
            "allow_unknown": True,
            "allow_negative": True,
            "allow_other": True,
            "schema_status": "fallback",
            "schema_error_code": error_code or "text_fallback_not_allowed",
        }
    )


def normalize_question_schema(
    question: GapPlannerQuestion,
    evidence_keys: List[str],
    needs_by_key: Dict[str, GapEvidenceNeed],
    reusable_by_key: Dict[str, UserEvidence],
    *,
    failure_stage: QuestionGenerationFailureStage = "initial_schema_invalid",
) -> GapPlannerQuestion:
    canonical_keys = list(
        dict.fromkeys(canonical_evidence_key(key) for key in evidence_keys)
    )
    evidence_groups = {
        needs_by_key[key].evidence_group
        for key in canonical_keys
        if key in needs_by_key and needs_by_key[key].evidence_group
    }
    evidence_group = evidence_groups.pop() if len(evidence_groups) == 1 else None
    group_relations = {
        needs_by_key[key].group_relation
        for key in canonical_keys
        if key in needs_by_key
    }
    group_relation: Literal["all", "any"] = (
        group_relations.pop() if len(group_relations) == 1 else "all"
    )
    structured_control_types = {
        "boolean",
        "boolean_group",
        "experience_form",
        "single_select",
        "multi_select",
        "number",
        "number_group",
        "date",
        "short_text",
    }
    if question.control_type not in structured_control_types:
        return invalid_structured_question_schema(
            question,
            canonical_keys,
            evidence_group=evidence_group,
            group_relation=group_relation,
            error_code=(
                "text_fallback_not_allowed"
                if question.control_type == "text_fallback"
                else "invalid_control_type"
            ),
            failure_stage=failure_stage,
        )
    if (
        question.control_type in {"boolean_group", "experience_form", "short_text"}
        and not question.question_id.startswith("policy:")
    ):
        return invalid_structured_question_schema(
            question,
            canonical_keys,
            evidence_group=evidence_group,
            group_relation=group_relation,
            error_code="backend_control_only",
            failure_stage=failure_stage,
        )

    language_selector_keys = {
        key
        for key in canonical_keys
        if needs_by_key[key].evidence_type == "language_score"
        or key == "education.language_medium"
    }
    is_language_proof_selector = (
        (
            group_relation == "any"
            or (group_relation == "all" and len(canonical_keys) == 1)
        )
        and bool(canonical_keys)
        and question.control_type == "single_select"
        and bool(question.options)
        and language_selector_keys == set(canonical_keys)
        and any(
            needs_by_key[key].evidence_type == "language_score"
            for key in canonical_keys
        )
    )
    if is_language_proof_selector:
        normalized_options = []
        seen_option_values = set()
        option_keys = set()
        for option in question.options:
            key = canonical_evidence_key(option.evidence_key or "")
            if key not in canonical_keys or option.value in seen_option_values:
                return invalid_structured_question_schema(
                    question,
                    canonical_keys,
                    evidence_group=evidence_group,
                    group_relation=group_relation,
                    error_code="invalid_evidence_key",
                    failure_stage=failure_stage,
                )
            need = needs_by_key[key]
            evidence_value = option.evidence_value
            if need.evidence_type != "language_score":
                required_fields = set(need.required_fields or ["description"])
                if "description" in required_fields:
                    evidence_value = {"description": option.label}
                elif "status" in required_fields:
                    evidence_value = {"status": True}
                else:
                    return invalid_structured_question_schema(
                        question,
                        canonical_keys,
                        evidence_group=evidence_group,
                        group_relation=group_relation,
                        error_code="invalid_option_value",
                        failure_stage=failure_stage,
                    )
            normalized_options.append(
                option.model_copy(
                    update={"evidence_key": key, "evidence_value": evidence_value}
                )
            )
            seen_option_values.add(option.value)
            option_keys.add(key)
        if option_keys != set(canonical_keys):
            return invalid_structured_question_schema(
                question,
                canonical_keys,
                evidence_group=evidence_group,
                group_relation=group_relation,
                error_code="missing_control_binding",
                failure_stage=failure_stage,
            )
        diagnostics = (
            question.generation_diagnostics
            or GapQuestionGenerationDiagnostics(
                requirement_id=question.requirement_id,
                allowed_evidence_keys=canonical_keys,
                group_relation=group_relation,
                initial_schema=question_schema_snapshot(question),
            )
        )
        return question.model_copy(
            update={
                "question": question.prompt or question.question,
                "prompt": question.prompt or question.question,
                "evidence_keys": canonical_keys,
                "expected_evidence_keys": canonical_keys,
                "allowed_evidence_keys": canonical_keys,
                "evidence_group": evidence_group,
                "group_relation": group_relation,
                "control_type": "single_select",
                "options": normalized_options,
                "fields": [],
                "validation": GapQuestionValidation(
                    required=True,
                    min_selections=1,
                    max_selections=1,
                ),
                "allow_unknown": True,
                "allow_negative": True,
                "schema_status": "valid",
                "schema_error_code": None,
                "generation_diagnostics": diagnostics,
            }
        )

    allowed_paths: Dict[str, set[str]] = {}
    requirement_paths: Dict[str, set[str]] = {}
    for key in canonical_keys:
        need = needs_by_key[key]
        requirement_paths[key] = set(need.required_fields or ["description"])
        existing = reusable_by_key.get(key)
        missing = (
            missing_evidence_fields(need, existing.value)
            if existing and existing.availability == "known"
            else list(need.required_fields or ["description"])
        )
        allowed_paths[key] = set(missing)

    normalized_fields = []
    seen_field_ids = set()
    for field in question.fields:
        key = canonical_evidence_key(field.evidence_key)
        if key not in canonical_keys or field.field_id in seen_field_ids:
            logger.warning(
                "invalid_gap_question_field_reference question_id=%s field_id=%s status=invalid",
                question.question_id,
                field.field_id,
            )
            return invalid_structured_question_schema(
                question,
                canonical_keys,
                evidence_group=evidence_group,
                group_relation=group_relation,
                error_code="invalid_evidence_key",
                failure_stage=failure_stage,
            )
        if field.value_path not in requirement_paths[key]:
            logger.warning(
                "invalid_gap_question_value_path question_id=%s key=%s path=%s status=invalid",
                question.question_id,
                key,
                field.value_path,
            )
            return invalid_structured_question_schema(
                question,
                canonical_keys,
                evidence_group=evidence_group,
                group_relation=group_relation,
                error_code="invalid_value_path",
                failure_stage=failure_stage,
            )
        if field.value_path not in allowed_paths[key]:
            continue
        normalized_fields.append(field.model_copy(update={"evidence_key": key}))
        seen_field_ids.add(field.field_id)

    normalized_options = []
    seen_option_values = set()
    for option in question.options:
        key = canonical_evidence_key(option.evidence_key or "")
        if not key and len(canonical_keys) == 1:
            key = canonical_keys[0]
        if key not in canonical_keys or option.value in seen_option_values:
            logger.warning(
                "invalid_gap_question_option_reference question_id=%s value=%r status=invalid",
                question.question_id,
                option.value,
            )
            return invalid_structured_question_schema(
                question,
                canonical_keys,
                evidence_group=evidence_group,
                group_relation=group_relation,
                error_code="invalid_evidence_key",
                failure_stage=failure_stage,
            )
        try:
            json.dumps(option.evidence_value, ensure_ascii=False)
        except (TypeError, ValueError):
            return invalid_structured_question_schema(
                question,
                canonical_keys,
                evidence_group=evidence_group,
                group_relation=group_relation,
                error_code="invalid_option_value",
                failure_stage=failure_stage,
            )
        normalized_options.append(option.model_copy(update={"evidence_key": key}))
        seen_option_values.add(option.value)

    controls_requiring_fields = {
        "boolean", "boolean_group", "number", "number_group", "date", "short_text"
    }
    controls_requiring_options = {"single_select", "multi_select"}
    if (
        question.control_type in controls_requiring_fields
        and not normalized_fields
    ) or (
        question.control_type in controls_requiring_options
        and not normalized_options
    ):
        logger.warning(
            "incomplete_gap_question_schema question_id=%s control=%s status=invalid",
            question.question_id,
            question.control_type,
        )
        return invalid_structured_question_schema(
            question,
            canonical_keys,
            evidence_group=evidence_group,
            group_relation=group_relation,
            error_code="missing_control_binding",
            failure_stage=failure_stage,
        )
    if question.control_type in {"boolean", "number", "date", "short_text"} and len(
        normalized_fields
    ) != 1:
        logger.warning(
            "invalid_gap_question_field_count question_id=%s control=%s status=invalid",
            question.question_id,
            question.control_type,
        )
        return invalid_structured_question_schema(
            question,
            canonical_keys,
            evidence_group=evidence_group,
            group_relation=group_relation,
            error_code="invalid_control_binding",
            failure_stage=failure_stage,
        )
    coverage_by_key: Dict[str, set[str]] = {
        key: set() for key in canonical_keys
    }
    for field in normalized_fields:
        coverage_by_key[field.evidence_key].add(field.value_path)
    for option in normalized_options:
        key = option.evidence_key or ""
        if isinstance(option.evidence_value, dict):
            coverage_by_key[key].update(
                path
                for path in option.evidence_value
                if path in requirement_paths[key]
            )
            subscores = option.evidence_value.get("subscores")
            if isinstance(subscores, dict):
                coverage_by_key[key].update(
                    path for path in subscores if path in requirement_paths[key]
                )
        elif "description" in requirement_paths[key]:
            coverage_by_key[key].add("description")

    if group_relation == "all":
        satisfiable = all(
            allowed_paths[key].issubset(coverage_by_key[key])
            for key in canonical_keys
        )
    else:
        satisfiable = any(
            allowed_paths[key]
            and allowed_paths[key].issubset(coverage_by_key[key])
            for key in canonical_keys
        )
    if not satisfiable:
        return invalid_structured_question_schema(
            question,
            canonical_keys,
            evidence_group=evidence_group,
            group_relation=group_relation,
            error_code="unsatisfied_required_slots",
            failure_stage=failure_stage,
        )

    safe_validation = question.validation.model_copy(
        update={
            "minimum": None,
            "maximum": None,
            "min_selections": (
                1
                if question.control_type in {"single_select", "multi_select"}
                and question.validation.required
                else None
            ),
            "max_selections": (
                1 if question.control_type == "single_select" else None
            ),
        }
    )
    diagnostics = (
        question.generation_diagnostics
        or GapQuestionGenerationDiagnostics(
            requirement_id=question.requirement_id,
            allowed_evidence_keys=canonical_keys,
            group_relation=group_relation,
            initial_schema=question_schema_snapshot(question),
        )
    )
    is_conditional_controller = bool(question.conditional_controller_bindings)
    terminal_actions_disabled = question.control_type in {
        "boolean_group", "experience_form", "short_text"
    } or (
        question.question_id.startswith("policy:")
        and not is_conditional_controller
        and bool(canonical_keys)
        and all(
            needs_by_key[key].evidence_type
            in {"material_status", "material_quantity"}
            or needs_by_key[key].other_value_kind is not None
            for key in canonical_keys
        )
    )
    return question.model_copy(
        update={
            "question": question.prompt or question.question,
            "prompt": question.prompt or question.question,
            "evidence_keys": canonical_keys,
            "expected_evidence_keys": canonical_keys,
            "allowed_evidence_keys": canonical_keys,
            "evidence_group": evidence_group,
            "group_relation": group_relation,
            "options": normalized_options,
            "fields": normalized_fields,
            "validation": safe_validation,
            # Terminal states are system-owned actions, not model-authored options.
            # A course checklist encodes explicit true/false per row, so neither
            # terminal action is part of that deterministic contract.
            "allow_unknown": not terminal_actions_disabled,
            "allow_negative": not terminal_actions_disabled,
            "schema_status": "valid",
            "schema_error_code": None,
            "generation_diagnostics": diagnostics,
        }
    )


GapPlannerFailureKind = Literal[
    "generation_incomplete",
    "malformed_json",
    "schema_validation_error",
    "business_validation_error",
]


class GapPlannerOutputError(Exception):
    def __init__(
        self,
        kind: GapPlannerFailureKind,
        message: str,
    ) -> None:
        super().__init__(message)
        self.kind = kind


def coerce_deepseek_text_result(value: Any) -> DeepSeekTextResult:
    if isinstance(value, DeepSeekTextResult):
        return value
    return DeepSeekTextResult(content=value if isinstance(value, str) else "")


def gap_planner_json_failure_kind(
    error: json.JSONDecodeError,
    result: DeepSeekTextResult,
) -> GapPlannerFailureKind:
    stop_reason = (result.stop_reason or "").casefold()
    incomplete_markers = (
        "unterminated string",
        "expecting value",
        "expecting ',' delimiter",
        "expecting property name enclosed in double quotes",
    )
    near_end = error.pos >= max(0, len(result.content.rstrip()) - 2)
    if (
        not result.content.strip()
        or stop_reason in {"length", "max_tokens", "max_output_tokens"}
        or (near_end and any(marker in error.msg.casefold() for marker in incomplete_markers))
    ):
        return "generation_incomplete"
    return "malformed_json"


def parse_gap_planner_output(result: DeepSeekTextResult) -> GapPlannerLLMOutput:
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError as error:
        kind = gap_planner_json_failure_kind(error, result)
        logger.warning(
            "gap_planner_parse_failed kind=%s parse_error_type=%s stop_reason=%s final_text_length=%d error_position=%d",
            kind,
            type(error).__name__,
            result.stop_reason,
            len(result.content),
            error.pos,
        )
        raise GapPlannerOutputError(kind, str(error)) from error
    try:
        return GapPlannerLLMOutput.model_validate(payload)
    except ValidationError as error:
        logger.warning(
            "gap_planner_parse_failed kind=schema_validation_error parse_error_type=%s stop_reason=%s final_text_length=%d validation_error_count=%d",
            type(error).__name__,
            result.stop_reason,
            len(result.content),
            len(error.errors()),
        )
        raise GapPlannerOutputError("schema_validation_error", str(error)) from error


def validate_gap_planner_business_output(
    output: GapPlannerLLMOutput,
    allowed_requirement_ids: Set[str],
) -> None:
    requirement_ids = [item.requirement_id for item in output.requirements]
    invalid_ids = sorted(set(requirement_ids) - allowed_requirement_ids)
    duplicate_ids = sorted(
        requirement_id
        for requirement_id in set(requirement_ids)
        if requirement_ids.count(requirement_id) > 1
    )
    if invalid_ids or duplicate_ids:
        logger.warning(
            "gap_planner_business_validation_failed invalid_requirement_id_count=%d duplicate_requirement_id_count=%d",
            len(invalid_ids),
            len(duplicate_ids),
        )
        raise GapPlannerOutputError(
            "business_validation_error",
            "Gap Planner returned invalid or duplicate requirement identifiers",
        )


def gap_planner_prompt_payload(
    request: GapPlanRequest,
    formal_requirements: List[Dict[str, Any]],
    reusable: List[UserEvidence],
) -> Dict[str, Any]:
    return {
        "target_program": {
            "university": request.target_program.university,
            "program": request.target_program.program,
            "intended_entry_year": request.target_program.intended_entry_year,
            "intended_entry_term": request.target_program.intended_entry_term,
        },
        "requirements": [
            {
                key: item.get(key)
                for key in (
                    "requirement_id",
                    "category",
                    "requirement",
                    "importance",
                    "requirement_verification_status",
                    "source_cycle",
                    "temporal_applicability",
                    "temporal_note",
                    "gap_eligibility",
                    "parent_requirement_id",
                    "parent_requirement_text",
                    "parent_has_explicit_conditional_scope",
                    "inherits_parent_applicability",
                )
            }
            for item in formal_requirements
        ],
        "authoritative_prerequisite_plan": [
            group.model_dump()
            for group in request.authoritative_prerequisite_plan
        ],
        "authoritative_course_credit_plan": [
            item.model_dump()
            for item in request.authoritative_course_credit_plan
        ],
        "canonical_user_evidence": [
            {
                "evidence_type": item.evidence_type,
                "key": canonical_evidence_key(item.key),
                "value": item.value,
                "availability": item.availability,
            }
            for item in reusable
            if not is_legacy_global_course_evidence_key(item.key)
        ],
    }


def materialize_gap_planner_output(
    output: GapPlannerLLMOutput,
) -> GapPlannerOutput:
    return GapPlannerOutput(
        requirements=[
            GapPlannerRequirementDraft(
                requirement_id=item.requirement_id,
                matchable=item.matchable,
                informational_reason=item.informational_reason,
                match_strategy=item.match_strategy,
                evidence_needs=[
                    GapEvidenceNeed(**need.model_dump())
                    for need in item.evidence_needs
                ],
                constraint=item.constraint,
                course_requirements=list(item.course_requirements),
                conditional=item.conditional,
                other_items=list(item.other_items),
            )
            for item in output.requirements
        ],
        questions=[
            GapPlannerQuestion(**question.model_dump())
            for question in output.questions
        ],
    )


def missing_structured_question(
    requirement: GapPlannedRequirement,
    missing_needs: List[GapEvidenceNeed],
    *,
    prompt: str,
) -> GapPlannerQuestion:
    allowed_keys = [need.key for need in missing_needs]
    group_relations = {need.group_relation for need in missing_needs}
    group_relation: Literal["all", "any"] = (
        group_relations.pop() if len(group_relations) == 1 else "all"
    )
    evidence_groups = {
        need.evidence_group for need in missing_needs if need.evidence_group
    }
    diagnostics = GapQuestionGenerationDiagnostics(
        requirement_id=requirement.requirement_id,
        allowed_evidence_keys=allowed_keys,
        group_relation=group_relation,
        initial_schema=None,
        initial_failure_stage="initial_schema_missing",
        initial_validator_error="initial_schema_missing",
    )
    log_question_generation_diagnostics("initial_missing", diagnostics)
    return GapPlannerQuestion(
        question_id=f"q:{requirement.requirement_id}",
        requirement_id=requirement.requirement_id,
        question=prompt,
        prompt=prompt,
        evidence_keys=allowed_keys,
        expected_evidence_keys=allowed_keys,
        allowed_evidence_keys=allowed_keys,
        evidence_group=(
            evidence_groups.pop() if len(evidence_groups) == 1 else None
        ),
        group_relation=group_relation,
        # Internal repair target only; it is never rendered before repair.
        control_type="boolean",
        schema_status="invalid",
        schema_error_code="initial_schema_missing",
        generation_diagnostics=diagnostics,
    )


def gap_question_generation_error(
    question: GapPlannerQuestion,
    *,
    final_failure_stage: Optional[QuestionGenerationFailureStage] = None,
    repair_validator_error: Optional[str] = None,
) -> GapPlannerQuestion:
    diagnostics = question.generation_diagnostics or GapQuestionGenerationDiagnostics(
        requirement_id=question.requirement_id,
        allowed_evidence_keys=list(question.allowed_evidence_keys),
        group_relation=question.group_relation,
        initial_schema=question_schema_snapshot(question),
    )
    final_stage = (
        final_failure_stage
        or diagnostics.repair_failure_stage
        or diagnostics.initial_failure_stage
        or "normalization_failed"
    )
    diagnostics = diagnostics.model_copy(
        update={
            "repair_validator_error": (
                repair_validator_error or diagnostics.repair_validator_error
            ),
            "final_failure_stage": final_stage,
        }
    )
    log_question_generation_diagnostics("final_failure", diagnostics)
    return question.model_copy(
        update={
            "question": "这个问题暂时无法生成，请重新尝试。",
            "prompt": "这个问题暂时无法生成，请重新尝试。",
            "control_type": "boolean",
            "options": [],
            "fields": [],
            "allow_unknown": False,
            "allow_negative": False,
            "allow_other": False,
            "schema_status": "generation_error",
            "repair_attempts": 1,
            "generation_diagnostics": diagnostics,
        }
    )


def gap_question_repair_context(
    question: GapPlannerQuestion,
    requirement: GapPlannedRequirement,
    reusable_by_key: Dict[str, UserEvidence],
) -> Dict[str, Any]:
    needs_by_key = {need.key: need for need in requirement.evidence_needs}
    allowed_keys = [
        key
        for key in question.allowed_evidence_keys
        if key in needs_by_key
    ]
    current_missing = []
    for key in allowed_keys:
        need = needs_by_key[key]
        existing = reusable_by_key.get(key)
        missing_fields = (
            missing_evidence_fields(need, existing.value)
            if existing and existing.availability == "known"
            else list(need.required_fields or ["description"])
        )
        current_missing.extend(f"{key}.{field}" for field in missing_fields)
    diagnostics = question.generation_diagnostics
    return {
        "question_id": question.question_id,
        "requirement_id": requirement.requirement_id,
        "requirement_summary": requirement.requirement,
        "allowed_evidence_keys": allowed_keys,
        "evidence_group": question.evidence_group,
        "group_relation": question.group_relation,
        "current_missing_evidence": current_missing,
        "invalid_schema": (
            diagnostics.initial_schema
            if diagnostics
            else question_schema_snapshot(question)
        ),
        "validator_error_reason": (
            diagnostics.initial_validator_error
            if diagnostics
            else question.schema_error_code
        ),
        "allowed_control_types": [
            "boolean",
            "single_select",
            "multi_select",
            "number",
            "number_group",
            "date",
        ],
    }


def question_with_repair_failure(
    question: GapPlannerQuestion,
    stage: QuestionGenerationFailureStage,
    error_code: str,
    *,
    repair_schema: Optional[Dict[str, Any]] = None,
) -> GapPlannerQuestion:
    diagnostics = question.generation_diagnostics or GapQuestionGenerationDiagnostics(
        requirement_id=question.requirement_id,
        allowed_evidence_keys=list(question.allowed_evidence_keys),
        group_relation=question.group_relation,
        initial_schema=question_schema_snapshot(question),
    )
    diagnostics = diagnostics.model_copy(
        update={
            "repair_schema": repair_schema,
            "repair_failure_stage": stage,
            "repair_validator_error": error_code,
        }
    )
    log_question_generation_diagnostics("repair_failure", diagnostics)
    return question.model_copy(
        update={
            "schema_status": "invalid",
            "schema_error_code": error_code,
            "generation_diagnostics": diagnostics,
        }
    )


def normalize_question_schema_safely(
    question: GapPlannerQuestion,
    evidence_keys: List[str],
    needs_by_key: Dict[str, GapEvidenceNeed],
    reusable_by_key: Dict[str, UserEvidence],
    *,
    repair_phase: bool = False,
) -> GapPlannerQuestion:
    try:
        return normalize_question_schema(
            question,
            evidence_keys,
            needs_by_key,
            reusable_by_key,
            failure_stage=(
                "repair_schema_invalid" if repair_phase else "initial_schema_invalid"
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        logger.warning(
            "gap_question_normalization_failed question_id=%s requirement_id=%s error_type=%s",
            question.question_id,
            question.requirement_id,
            type(error).__name__,
        )
        if repair_phase:
            return question_with_repair_failure(
                question,
                "normalization_failed",
                type(error).__name__,
                repair_schema=question_schema_snapshot(question),
            )
        group_relations = {
            needs_by_key[key].group_relation
            for key in evidence_keys
            if key in needs_by_key
        }
        group_relation: Literal["all", "any"] = (
            group_relations.pop() if len(group_relations) == 1 else "all"
        )
        evidence_groups = {
            needs_by_key[key].evidence_group
            for key in evidence_keys
            if key in needs_by_key and needs_by_key[key].evidence_group
        }
        return invalid_structured_question_schema(
            question,
            evidence_keys,
            evidence_group=(
                evidence_groups.pop() if len(evidence_groups) == 1 else None
            ),
            group_relation=group_relation,
            error_code=type(error).__name__,
            failure_stage="normalization_failed",
        )


ACADEMIC_POLICY_KEYS = {
    "degree_classification",
    "gpa",
    "average_score",
}


def build_backend_academic_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        supported = [
            need
            for need in requirement.evidence_needs
            if need.evidence_type == "academic_score"
            and canonical_evidence_key(need.key).rsplit(".", 1)[-1]
            in ACADEMIC_POLICY_KEYS
        ]
        if not supported:
            continue
        any_groups: Dict[str, List[GapEvidenceNeed]] = {}
        for need in requirement.evidence_needs:
            if need.evidence_group and need.group_relation == "any":
                any_groups.setdefault(need.evidence_group, []).append(need)
        satisfied_groups = {
            group
            for group, group_needs in any_groups.items()
            if any(need.already_known for need in group_needs)
        }
        missing_supported = []
        for need in supported:
            covered_keys.add(need.key)
            if need.already_known or need.evidence_group in satisfied_groups:
                continue
            missing_supported.append(need)

        classification_needs = [
            need
            for need in missing_supported
            if canonical_evidence_key(need.key).rsplit(".", 1)[-1]
            == "degree_classification"
        ]
        for need in classification_needs:
            question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:degree-classification",
                requirement_id=requirement.requirement_id,
                prompt="请选择你的学位等级。",
                expected_evidence_keys=[need.key],
                control_type="single_select",
                options=[
                    GapQuestionOption(
                        value=value,
                        label=label,
                        evidence_key=need.key,
                        evidence_value={"description": description},
                    )
                    for value, label, description in (
                        ("first", "First", "First"),
                        ("upper_second", "2:1 / Upper Second", "2:1"),
                        ("lower_second", "2:2 / Lower Second", "2:2"),
                        ("third", "Third", "Third"),
                        ("other", "Other", "Other"),
                    )
                ],
                allow_other=True,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Academic Question Policy produced an invalid degree classification schema"
                )
            questions.append(normalized)

        numeric_needs = [
            need
            for need in missing_supported
            if canonical_evidence_key(need.key).rsplit(".", 1)[-1]
            in {"gpa", "average_score"}
        ]
        numeric_groups: Dict[str, List[GapEvidenceNeed]] = {}
        for need in numeric_needs:
            group_key = need.evidence_group or f"{requirement.requirement_id}:{need.key}"
            numeric_groups.setdefault(group_key, []).append(need)
        for index, group_needs in enumerate(numeric_groups.values()):
            fields = []
            for need in group_needs:
                key_leaf = canonical_evidence_key(need.key).rsplit(".", 1)[-1]
                label = "GPA" if key_leaf == "gpa" else "平均分"
                fields.extend(
                    [
                        GapQuestionField(
                            field_id=f"{key_leaf}-score",
                            label=f"{label}分数",
                            evidence_key=need.key,
                            value_path="score",
                        ),
                        GapQuestionField(
                            field_id=f"{key_leaf}-scale",
                            label=f"{label}满分",
                            evidence_key=need.key,
                            value_path="scale",
                        ),
                    ]
                )
            labels = [
                "GPA"
                if canonical_evidence_key(need.key).rsplit(".", 1)[-1] == "gpa"
                else "平均分"
                for need in group_needs
            ]
            question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:academic-numeric:{index}",
                requirement_id=requirement.requirement_id,
                prompt=f"请提供你的{'或'.join(labels)}。",
                expected_evidence_keys=[need.key for need in group_needs],
                control_type=("number" if len(fields) == 1 else "number_group"),
                fields=fields,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key for need in group_needs],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Academic Question Policy produced an invalid numeric schema"
                )
            questions.append(normalized)
    return questions, covered_keys


LANGUAGE_POLICY_PROOFS: Dict[str, tuple[LanguageProofKind, str]] = {
    "ielts": ("scored_test", "IELTS"),
    "toefl": ("scored_test", "TOEFL"),
    "education.language_medium": ("medium_of_instruction", "英语授课证明"),
}


def backend_language_proof(need: GapEvidenceNeed) -> Optional[tuple[LanguageProofKind, str]]:
    canonical_key = canonical_evidence_key(need.key)
    configured = LANGUAGE_POLICY_PROOFS.get(canonical_key)
    if configured is None or need.proof_kind != configured[0]:
        return None
    return configured


def evidence_is_complete_known(
    need: GapEvidenceNeed,
    item: Optional[UserEvidence],
) -> bool:
    return bool(
        item
        and item.availability == "known"
        and not missing_evidence_fields(need, item.value)
    )


def build_backend_language_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        language_needs = [
            need
            for need in requirement.evidence_needs
            if need.evidence_type == "language_score"
            or need.proof_kind is not None
        ]
        if not language_needs:
            continue
        supported = [
            need for need in language_needs if backend_language_proof(need) is not None
        ]
        if not supported:
            continue

        relation = requirement.constraint.relation
        if relation == "any" and len(supported) != len(language_needs):
            # Keep a partially understood alternative group under one producer.
            continue

        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        policy_groups = [supported] if relation == "any" else [[need] for need in supported]
        for index, group_needs in enumerate(policy_groups):
            covered_keys.update(need.key for need in group_needs)
            existing_by_key = {
                need.key: reusable_by_key.get(canonical_evidence_key(need.key))
                for need in group_needs
            }
            if relation == "any" and any(
                evidence_is_complete_known(need, existing_by_key[need.key])
                for need in group_needs
            ):
                continue

            partial_known = [
                need
                for need in group_needs
                if (item := existing_by_key[need.key]) is not None
                and item.availability == "known"
                and not evidence_is_complete_known(need, item)
            ]
            if relation == "any" and partial_known:
                active_needs = partial_known
            else:
                active_needs = [
                    need
                    for need in group_needs
                    if not evidence_is_complete_known(
                        need, existing_by_key[need.key]
                    )
                    and (
                        (item := existing_by_key[need.key]) is None
                        or item.availability not in {"known_negative", "unknown"}
                    )
                ]
            if not active_needs:
                continue

            options = []
            for need in active_needs:
                proof_kind, label = backend_language_proof(need) or (None, "")
                options.append(
                    GapQuestionOption(
                        value=canonical_evidence_key(need.key),
                        label=label,
                        evidence_key=need.key,
                        evidence_value=(
                            {"description": label}
                            if proof_kind == "medium_of_instruction"
                            else None
                        ),
                    )
                )
            prompt = (
                "你准备使用哪种语言能力证明？"
                if len(active_needs) > 1
                else f"请确认你将使用{options[0].label}作为语言能力证明。"
            )
            if requirement.requirement_verification_status == "model_memory_unverified":
                prompt = f"根据目前的 AI 参考信息，该项目可能有相关要求。{prompt}"
            question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:language-proof:{index}",
                requirement_id=requirement.requirement_id,
                prompt=prompt,
                expected_evidence_keys=[need.key for need in active_needs],
                group_relation=relation,
                control_type="single_select",
                options=options,
                fields=[],
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key for need in active_needs],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Language Question Policy produced an invalid selector schema"
                )
            questions.append(normalized)
    return questions, covered_keys


def build_backend_course_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        if requirement.category != "course":
            continue
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        item_needs = [
            needs_by_key.get(gap_course_item_evidence_key(item))
            for item in requirement.course_requirements
        ]
        item_needs = [need for need in item_needs if need is not None]
        total_credit_keys = {
            canonical_evidence_key(option.key)
            for option in requirement.constraint.options
            if (option.kind or requirement.constraint.kind) == "course_credit"
            and option.required_quantity is not None
            and option.unit
        }
        total_credit_needs = [
            need
            for need in requirement.evidence_needs
            if need.key in total_credit_keys
        ]
        item_credit_needs = [
            needs_by_key.get(course_requirement_credit_evidence_key(item.item_id))
            for item in requirement.course_requirements
            if item.minimum_credits is not None and item.unit
        ]
        item_credit_needs = [need for need in item_credit_needs if need is not None]
        if not item_needs and not total_credit_needs and not item_credit_needs:
            continue

        covered_keys.update(need.key for need in item_needs)
        covered_keys.update(need.key for need in total_credit_needs)
        covered_keys.update(need.key for need in item_credit_needs)
        covered_keys.update(item.evidence_key for item in requirement.course_requirements)

        missing_items = [
            need
            for need in item_needs
            if not need.already_known
            and not (
                (existing := reusable_by_key.get(need.key))
                and evidence_is_terminal_for_need(need, existing)
            )
        ]
        if missing_items:
            checklist = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:course-checklist",
                requirement_id=requirement.requirement_id,
                prompt="请确认你是否修过能够覆盖以下要求的课程。",
                expected_evidence_keys=[need.key for need in missing_items],
                control_type="boolean_group",
                fields=[
                    GapQuestionField(
                        field_id=need.key.rsplit(".", 1)[-1],
                        label=need.label,
                        evidence_key=need.key,
                        value_path="completed",
                    )
                    for need in missing_items
                ],
                allow_unknown=False,
                allow_negative=False,
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                checklist,
                [need.key for need in missing_items],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Course Question Policy produced an invalid checklist schema"
                )
            questions.append(normalized)

        credit_needs = [
            need
            for need in [*total_credit_needs, *item_credit_needs]
            if not need.already_known
            and not (
                (existing := reusable_by_key.get(need.key))
                and evidence_is_terminal_for_need(need, existing)
            )
        ]
        for index, need in enumerate(credit_needs):
            unit = need.unit or "credits"
            prompt = f"{need.label or '这些相关课程'}合计多少 {unit}？"
            credit_question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:course-credit:{index}",
                requirement_id=requirement.requirement_id,
                prompt=prompt,
                expected_evidence_keys=[need.key],
                control_type="number",
                fields=[
                    GapQuestionField(
                        field_id=f"{need.key.rsplit('.', 1)[-1]}-quantity",
                        label=f"{need.label or '相关课程'}（{unit}）",
                        evidence_key=need.key,
                        value_path="quantity",
                    )
                ],
                validation=GapQuestionValidation(required=True, minimum=0),
                allow_unknown=True,
                allow_negative=False,
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                credit_question,
                [need.key],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Course Question Policy produced an invalid credit schema"
                )
            questions.append(normalized)
    return questions, covered_keys


GRE_POLICY_FIELDS: tuple[tuple[GREScoreComponent, str], ...] = (
    ("verbal", "Verbal Reasoning"),
    ("quantitative", "Quantitative Reasoning"),
    ("analytical_writing", "Analytical Writing"),
)


def build_backend_gre_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        gre_need = next(
            (
                need
                for need in requirement.evidence_needs
                if need.evidence_type == "standardized_score"
                and canonical_evidence_key(need.key) == "gre"
            ),
            None,
        )
        if gre_need is None:
            continue
        covered_keys.add(gre_need.key)
        if gre_need.group_relation == "any" and any(
            evidence_is_complete_known(
                sibling,
                reusable_by_key.get(canonical_evidence_key(sibling.key)),
            )
            for sibling in requirement.evidence_needs
            if sibling.evidence_group == gre_need.evidence_group
        ):
            continue
        existing = reusable_by_key.get(gre_need.key)
        missing_fields = (
            missing_evidence_fields(gre_need, existing.value)
            if existing and existing.availability == "known"
            else list(gre_need.required_fields)
        )
        if not missing_fields or (
            existing and existing.availability in {"known_negative", "unknown"}
        ):
            continue

        labels = dict(GRE_POLICY_FIELDS)
        threshold_by_component = {
            option.component: option.minimum
            for option in requirement.constraint.options
            if canonical_evidence_key(option.key) == "gre"
            and option.component is not None
            and option.minimum is not None
        }
        fields = [
            GapQuestionField(
                field_id=f"gre-{component}",
                label=(
                    f"{labels[component]}（项目要求 ≥ {threshold_by_component[component]:g}）"
                    if component in threshold_by_component
                    else labels[component]
                ),
                evidence_key=gre_need.key,
                value_path=component,
            )
            for component in (item[0] for item in GRE_POLICY_FIELDS)
            if component in missing_fields
        ]
        question = GapPlannerQuestion(
            question_id=f"policy:{requirement.requirement_id}:gre-score",
            requirement_id=requirement.requirement_id,
            prompt="请填写你的 GRE 成绩。",
            expected_evidence_keys=[gre_need.key],
            control_type="number" if len(fields) == 1 else "number_group",
            fields=fields,
            validation=GapQuestionValidation(required=True, minimum=0),
            allow_other=False,
        )
        normalized = normalize_question_schema_safely(
            question,
            [gre_need.key],
            {gre_need.key: gre_need},
            reusable_by_key,
        )
        if normalized.schema_status != "valid":
            raise RuntimeError(
                "Backend GRE Question Policy produced an invalid score schema"
            )
        questions.append(normalized)
    return questions, covered_keys


EXPERIENCE_POLICY_OPTIONS: tuple[tuple[str, str, Optional[ExperienceType]], ...] = (
    ("experience:work", "工作经历", "work"),
    ("experience:internship", "实习经历", "internship"),
    ("experience:research", "研究经历", "research"),
    ("experience:project", "项目经历", "project"),
    ("experience:other", "其他", "other"),
    ("experience:none", "没有相关经历", None),
)


def build_backend_experience_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        experience_need = next(
            (
                need
                for need in requirement.evidence_needs
                if need.evidence_type == "experience"
                and canonical_evidence_key(need.key) == "experience"
            ),
            None,
        )
        if experience_need is None:
            continue
        covered_keys.add(experience_need.key)
        existing = reusable_by_key.get("experience")
        if existing and existing.availability in {"known_negative", "unknown"}:
            continue
        missing_fields = (
            missing_evidence_fields(experience_need, existing.value)
            if existing and existing.availability == "known"
            else list(experience_need.required_fields)
        )
        if not missing_fields:
            continue

        needs_types = bool(
            {"has_experience", "experience_types"}.intersection(missing_fields)
        )
        needs_duration = bool({"duration", "unit"}.intersection(missing_fields))
        options = []
        if needs_types:
            for value, label, experience_type in EXPERIENCE_POLICY_OPTIONS:
                options.append(
                    GapQuestionOption(
                        value=value,
                        label=label,
                        evidence_key="experience",
                        evidence_value=(
                            {
                                "has_experience": False,
                                "experience_types": [],
                                "duration": None,
                                "unit": None,
                            }
                            if experience_type is None
                            else {
                                "has_experience": True,
                                "experience_types": [experience_type],
                            }
                        ),
                    )
                )
        if needs_duration:
            options.extend(
                [
                    GapQuestionOption(
                        value=f"unit:{unit}",
                        label=label,
                        evidence_key="experience",
                        evidence_value={"unit": unit},
                    )
                    for unit, label in (("months", "个月"), ("years", "年"))
                ]
            )
        fields = (
            [
                GapQuestionField(
                    field_id="experience-duration",
                    label="累计时长",
                    evidence_key="experience",
                    value_path="duration",
                )
            ]
            if needs_duration
            else []
        )
        question = GapPlannerQuestion(
            question_id=f"policy:{requirement.requirement_id}:experience-form",
            requirement_id=requirement.requirement_id,
            prompt="请提供与你申请方向相关的经验类型和累计时长。",
            expected_evidence_keys=["experience"],
            control_type="experience_form",
            options=options,
            fields=fields,
            allow_unknown=False,
            allow_negative=False,
            allow_other=False,
        )
        normalized = normalize_question_schema_safely(
            question,
            ["experience"],
            {"experience": experience_need},
            reusable_by_key,
        )
        if normalized.schema_status != "valid":
            raise RuntimeError(
                "Backend Experience Question Policy produced an invalid form schema"
            )
        questions.append(normalized)
    return questions, covered_keys


def build_backend_material_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        if requirement.category != "materials":
            continue
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        checklist_needs = [
            need
            for need in requirement.evidence_needs
            if need.evidence_type == "material_status"
            and need.material_type is not None
            and need.material_type != "recommendation_letters"
            and need.item_id
        ]
        recommendation_needs = [
            need
            for need in requirement.evidence_needs
            if need.evidence_type == "material_quantity"
            and need.material_type == "recommendation_letters"
            and need.item_id
        ]
        supported = [*checklist_needs, *recommendation_needs]
        if not supported:
            continue
        covered_keys.update(need.key for need in supported)

        missing_checklist = [
            need
            for need in checklist_needs
            if not (
                (existing := reusable_by_key.get(need.key))
                and existing.availability in {"known", "known_negative", "unknown"}
            )
        ]
        if missing_checklist:
            question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:materials-checklist",
                requirement_id=requirement.requirement_id,
                prompt="请确认你目前是否已经有以下可用于申请的材料。",
                expected_evidence_keys=[need.key for need in missing_checklist],
                control_type="boolean_group",
                fields=[
                    GapQuestionField(
                        field_id=need.item_id or need.key,
                        label=need.label,
                        evidence_key=need.key,
                        value_path="status",
                    )
                    for need in missing_checklist
                ],
                allow_unknown=False,
                allow_negative=False,
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key for need in missing_checklist],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Materials Question Policy produced an invalid checklist schema"
                )
            questions.append(normalized)

        for index, need in enumerate(recommendation_needs):
            existing = reusable_by_key.get(need.key)
            if existing and existing.availability in {
                "known",
                "known_negative",
                "unknown",
            }:
                continue
            threshold = need.required_quantity
            label = (
                f"已确认的推荐人数（项目要求 {threshold:g} 位）"
                if threshold is not None
                else "已确认的推荐人数"
            )
            question = GapPlannerQuestion(
                question_id=(
                    f"policy:{requirement.requirement_id}:recommendation-count:{index}"
                ),
                requirement_id=requirement.requirement_id,
                prompt="目前已经确认愿意为你提供推荐信的推荐人有几位？",
                expected_evidence_keys=[need.key],
                control_type="number",
                fields=[
                    GapQuestionField(
                        field_id=f"{need.item_id}-quantity",
                        label=label,
                        evidence_key=need.key,
                        value_path="quantity",
                    )
                ],
                validation=GapQuestionValidation(required=True, minimum=0),
                allow_unknown=False,
                allow_negative=False,
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Materials Question Policy produced an invalid recommendation schema"
                )
            questions.append(normalized)
    return questions, covered_keys


def build_backend_conditional_controller_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
    already_covered_keys: Set[str],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        if requirement.conditional_state != "pending":
            continue
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        controlling_keys = {
            canonical_evidence_key(key)
            for key in requirement.conditional.controlling_evidence_keys
        }
        predicates_by_key: Dict[str, List[GapConditionalPredicate]] = {}
        for predicate in requirement.conditional.predicates:
            predicates_by_key.setdefault(
                canonical_evidence_key(predicate.evidence_key), []
            ).append(predicate)
        for other_item in requirement.other_items:
            need = needs_by_key.get(other_item.evidence_key)
            if (
                need is None
                or need.key not in controlling_keys
                or need.key in already_covered_keys
            ):
                continue
            controller_predicates = predicates_by_key.get(need.key, [])
            if other_item.value_kind not in {
                "boolean", "single_select", "multi_select"
            }:
                logger.warning(
                    "conditional_controller_unsupported_other_kind requirement_id=%s key=%s kind=%s skipped=true",
                    requirement.requirement_id,
                    need.key,
                    other_item.value_kind,
                )
                continue
            if other_item.value_kind == "boolean" and not (
                len(controller_predicates) == 1
                and controller_predicates[0].operator == "equals"
                and len(controller_predicates[0].expected_values) == 1
            ):
                logger.warning(
                    "conditional_controller_boolean_predicate_unsupported requirement_id=%s key=%s skipped=true",
                    requirement.requirement_id,
                    need.key,
                )
                continue
            covered_keys.add(need.key)
            existing = reusable_by_key.get(need.key)
            if existing and evidence_is_terminal_for_need(need, existing):
                continue
            options = [
                GapQuestionOption(
                    value=option,
                    label=option,
                    evidence_key=need.key,
                    evidence_value={"description": option},
                )
                for option in other_item.options
            ]
            fields = (
                [
                    GapQuestionField(
                        field_id=other_item.item_id,
                        label=other_item.label,
                        evidence_key=need.key,
                        value_path="status",
                    )
                ]
                if other_item.value_kind == "boolean"
                else []
            )
            control_type = (
                "boolean"
                if other_item.value_kind == "boolean"
                else other_item.value_kind
            )
            prompt = (
                f"请确认：{other_item.label}。"
                if other_item.value_kind == "boolean"
                else f"请选择你的{other_item.label}。"
            )
            question = GapPlannerQuestion(
                question_id=(
                    f"policy:{requirement.requirement_id}:conditional-controller:"
                    f"{other_item.item_id}"
                ),
                requirement_id=requirement.requirement_id,
                prompt=prompt,
                expected_evidence_keys=[need.key],
                control_type=control_type,
                options=options,
                fields=fields,
                validation=GapQuestionValidation(
                    required=True,
                    min_selections=(1 if options else None),
                    max_selections=(1 if control_type == "single_select" else None),
                ),
                allow_unknown=True,
                allow_negative=True,
                allow_other=False,
                conditional_controller_bindings=[
                    GapConditionalControllerBinding(
                        evidence_key=need.key,
                        operator=predicate.operator,
                        expected_values=list(predicate.expected_values),
                    )
                    for predicate in controller_predicates
                ],
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Conditional Controller Policy produced an invalid schema"
                )
            questions.append(normalized)
    return questions, covered_keys


def build_backend_other_questions(
    planned: List[GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], Set[str]]:
    questions: List[GapPlannerQuestion] = []
    covered_keys: Set[str] = set()
    for requirement in planned:
        if not requirement.other_items:
            continue
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        for other_item in requirement.other_items:
            need = needs_by_key.get(other_item.evidence_key)
            if need is None:
                continue
            covered_keys.add(need.key)
            existing = reusable_by_key.get(need.key)
            if existing and existing.availability == "known" and not missing_evidence_fields(
                need, existing.value
            ):
                continue
            control_type = {
                "boolean": "boolean",
                "numeric": "number",
                "single_select": "single_select",
                "multi_select": "multi_select",
                "short_text": "short_text",
            }[other_item.value_kind]
            options = []
            fields = []
            if other_item.value_kind in {"single_select", "multi_select"}:
                options = [
                    GapQuestionOption(
                        value=option,
                        label=option,
                        evidence_key=need.key,
                        evidence_value={"description": option},
                    )
                    for option in other_item.options
                ]
            else:
                fields = [
                    GapQuestionField(
                        field_id=other_item.item_id,
                        label=other_item.label,
                        evidence_key=need.key,
                        value_path=(
                            "status"
                            if other_item.value_kind == "boolean"
                            else "quantity"
                            if other_item.value_kind == "numeric"
                            else "description"
                        ),
                    )
                ]
            prompt = {
                "boolean": f"你目前是否已经有或已完成{other_item.label}？",
                "numeric": f"请提供{other_item.label}的实际数值。",
                "single_select": f"请选择你的{other_item.label}。",
                "multi_select": f"请选择所有适用的{other_item.label}。",
                "short_text": f"请填写{other_item.label}。",
            }[other_item.value_kind]
            question = GapPlannerQuestion(
                question_id=f"policy:{requirement.requirement_id}:other:{other_item.item_id}",
                requirement_id=requirement.requirement_id,
                prompt=prompt,
                expected_evidence_keys=[need.key],
                control_type=control_type,
                options=options,
                fields=fields,
                validation=GapQuestionValidation(
                    required=True,
                    minimum=(0 if other_item.value_kind == "numeric" else None),
                    min_selections=(
                        1
                        if other_item.value_kind in {"single_select", "multi_select"}
                        else None
                    ),
                    max_selections=(
                        1 if other_item.value_kind == "single_select" else None
                    ),
                ),
                allow_unknown=False,
                allow_negative=False,
                allow_other=False,
            )
            normalized = normalize_question_schema_safely(
                question,
                [need.key],
                needs_by_key,
                reusable_by_key,
            )
            if normalized.schema_status != "valid":
                raise RuntimeError(
                    "Backend Other Question Policy produced an invalid schema"
                )
            questions.append(normalized)
    return questions, covered_keys


async def repair_gap_questions_once(
    questions: List[GapPlannerQuestion],
    requirements_by_id: Dict[str, GapPlannedRequirement],
    reusable_by_key: Dict[str, UserEvidence],
) -> tuple[List[GapPlannerQuestion], int]:
    invalid_questions = [
        question
        for question in questions
        if question.schema_status != "valid"
    ]
    if not invalid_questions:
        return questions, 0
    contexts = [
        gap_question_repair_context(
            question,
            requirements_by_id[question.requirement_id],
            reusable_by_key,
        )
        for question in invalid_questions
        if question.requirement_id in requirements_by_id
    ]
    if not contexts:
        return [
            gap_question_generation_error(
                question_with_repair_failure(
                    question,
                    "ownership_failed",
                    "repair_requirement_ownership_missing",
                ),
                final_failure_stage="ownership_failed",
            )
            if question in invalid_questions
            else question
            for question in questions
        ], 0
    prompt = (
        "你是 Structured Adaptive Interview Question Schema Repair。不要联网，不重新规划 Gap，"
        "只修复输入中的 invalid question schemas。每个 question 必须保持原 requirement_id、"
        "question_id、allowed evidence keys 和 evidence group；不得添加新 evidence key。"
        "control_type 只能使用 boolean、single_select、multi_select、number、number_group、date，"
        "禁止 text_fallback。ALL 的每个 missing slot 都必须有输入路径；ANY 至少提供一个完整"
        "合法 branch。语言证明 ANY group 的第一问必须修复成 selector-only single_select，"
        "每个 proof branch 一个 option 且 fields=[]；不得同时采集考试成绩。"
        "只输出修复后的 questions JSON。\n\n"
        f"Repair Contexts：{json.dumps(contexts, ensure_ascii=False)}\n"
        f"输出 JSON Schema：{json.dumps(GapQuestionRepairOutput.model_json_schema(), ensure_ascii=False)}\n"
        "只输出 JSON，不要解释。"
    )
    try:
        content = await call_deepseek(
            messages=[
                {
                    "role": "system",
                    "content": "只输出完整合法的 Question Schema JSON，不使用任何工具。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=3500,
            response_format={"type": "json_object"},
        )
    except HTTPException as error:
        logger.warning(
            "gap_question_schema_repair_failed stage=repair_generation_failed error_type=%s question_count=%d",
            type(error).__name__,
            len(invalid_questions),
        )
        return [
            gap_question_generation_error(
                question_with_repair_failure(
                    question,
                    "repair_generation_failed",
                    type(error).__name__,
                ),
                final_failure_stage="repair_generation_failed",
            )
            if question in invalid_questions
            else question
            for question in questions
        ], 1
    try:
        repaired_output = GapQuestionRepairOutput.model_validate_json(content)
    except ValidationError as error:
        parsed_schema: Optional[Dict[str, Any]] = None
        try:
            candidate_json = json.loads(content)
            if isinstance(candidate_json, dict):
                parsed_schema = candidate_json
        except (TypeError, ValueError):
            pass
        logger.warning(
            "gap_question_schema_repair_failed stage=repair_schema_invalid error_type=%s question_count=%d",
            type(error).__name__,
            len(invalid_questions),
        )
        return [
            gap_question_generation_error(
                question_with_repair_failure(
                    question,
                    "repair_schema_invalid",
                    "repair_output_schema_validation_failed",
                    repair_schema=parsed_schema,
                ),
                final_failure_stage="repair_schema_invalid",
            )
            if question in invalid_questions
            else question
            for question in questions
        ], 1

    repaired_by_id = {
        question.question_id: question for question in repaired_output.questions
    }
    result = []
    for question in questions:
        if question not in invalid_questions:
            result.append(question)
            continue
        draft = repaired_by_id.get(question.question_id)
        requirement = requirements_by_id.get(question.requirement_id or "")
        if draft is None:
            result.append(
                gap_question_generation_error(
                    question_with_repair_failure(
                        question,
                        "repair_schema_missing",
                        "repair_question_id_missing",
                    ),
                    final_failure_stage="repair_schema_missing",
                )
            )
            continue
        if requirement is None:
            result.append(
                gap_question_generation_error(
                    question_with_repair_failure(
                        question,
                        "ownership_failed",
                        "repair_requirement_ownership_missing",
                        repair_schema=draft.model_dump(mode="json"),
                    ),
                    final_failure_stage="ownership_failed",
                )
            )
            continue
        needs_by_key = {need.key: need for need in requirement.evidence_needs}
        allowed_keys = [
            key for key in question.allowed_evidence_keys if key in needs_by_key
        ]
        repair_diagnostics = (
            question.generation_diagnostics or GapQuestionGenerationDiagnostics()
        ).model_copy(
            update={"repair_schema": draft.model_dump(mode="json")}
        )
        candidate = normalize_question_schema_safely(
            GapPlannerQuestion(**draft.model_dump()).model_copy(
                update={
                    "question_id": question.question_id,
                    "requirement_id": question.requirement_id,
                    "generation_diagnostics": repair_diagnostics,
                }
            ),
            allowed_keys,
            needs_by_key,
            reusable_by_key,
            repair_phase=True,
        )
        if candidate.schema_status != "valid":
            final_stage = (
                candidate.generation_diagnostics.repair_failure_stage
                if candidate.generation_diagnostics
                and candidate.generation_diagnostics.repair_failure_stage
                else "repair_schema_invalid"
            )
            result.append(
                gap_question_generation_error(
                    candidate,
                    final_failure_stage=final_stage,
                    repair_validator_error=candidate.schema_error_code,
                )
            )
            continue
        result.append(candidate.model_copy(update={"repair_attempts": 1}))
    return result, 1


def trusted_reviewed_requirements(
    review: TargetProgramRequirementsReview,
) -> List[Dict[str, Any]]:
    return [
        {
            "requirement_id": f"{category.category}:{index}",
            "category": category.category,
            "requirement": requirement.requirement,
            "requirement_zh": requirement.requirement_zh,
            "importance": requirement.importance,
            "source_url": requirement.source_url,
            "verification_status": requirement.verification_status,
            "applicability_stage": requirement.applicability_stage,
        }
        for category in review.categories
        for index, requirement in enumerate(category.requirements)
        if requirement.verification_status in {"official_verified", "user_supplied"}
        and requirement.applicability_stage == "pre_admission"
    ]


def special_evidence_slug(label: str) -> str:
    normalized = unicodedata.normalize("NFKC", label).casefold().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if slug:
        return slug
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def special_evidence_key(item_type: str, canonical_label: str) -> str:
    prefix = (
        "prerequisite_course"
        if item_type == "prerequisite_course"
        else "objective_special"
    )
    return f"{prefix}:{special_evidence_slug(canonical_label)}"


def authoritative_prerequisite_item_id(
    requirement_id: str,
    prerequisite_kind: Literal["concrete_course", "course_category"],
    source_identity: str,
) -> str:
    """Build a stable id inside one Requirement; never an equivalence identity."""
    normalized_source = " ".join(
        unicodedata.normalize("NFKC", source_identity).casefold().split()
    )
    digest = hashlib.sha256(
        f"{requirement_id}\n{prerequisite_kind}\n{normalized_source}".encode("utf-8")
    ).hexdigest()[:16]
    return f"course-{digest}"


def prerequisite_course_code(label: str) -> Optional[str]:
    match = re.match(r"^([A-Za-z]{2,}\d{3,}[A-Za-z]?)\b", label.strip())
    return match.group(1).upper() if match else None


def programme_course_evidence_key(
    target_program: TargetProgram,
    requirement_id: str,
    item_id: str,
) -> str:
    identity = target_program_cache_identity(target_program)
    programme_scope = programme_cache_key(identity)[:20]
    requirement_scope = hashlib.sha256(
        requirement_id.strip().casefold().encode("utf-8")
    ).hexdigest()[:12]
    return f"programme_course_response:{programme_scope}:{requirement_scope}:{item_id}"


def authoritative_course_credit_item_id(
    requirement_id: str,
    required_quantity: float,
    unit: str,
) -> str:
    normalized = "\n".join(
        [
            requirement_id.strip().casefold(),
            f"{required_quantity:g}",
            " ".join(unicodedata.normalize("NFKC", unit).casefold().split()),
        ]
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"course-credit-{digest}"


def programme_course_credit_evidence_key(
    target_program: TargetProgram,
    requirement_id: str,
    item_id: str,
) -> str:
    identity = target_program_cache_identity(target_program)
    programme_scope = programme_cache_key(identity)[:20]
    requirement_scope = hashlib.sha256(
        requirement_id.strip().casefold().encode("utf-8")
    ).hexdigest()[:12]
    return (
        f"programme_course_credit_response:{programme_scope}:"
        f"{requirement_scope}:{item_id}"
    )


def gap_course_item_evidence_key(item: GapCourseRequirement) -> str:
    return (
        canonical_evidence_key(item.evidence_key)
        if item.authoritative
        else course_requirement_evidence_key(item.item_id)
    )


def is_legacy_global_course_evidence_key(key: str) -> bool:
    canonical = canonical_evidence_key(key)
    return canonical.startswith(
        ("prerequisite_course:", "course_category_response:", "user_course:")
    )


def special_course_category_context_key(
    target_program: TargetProgram,
    requirement_id: str,
    category_label: str,
) -> str:
    identity = "\n".join(
        [
            target_program.university.strip().casefold(),
            target_program.program.strip().casefold(),
            target_program.official_program_url.strip().casefold().rstrip("/"),
            str(target_program.intended_entry_year),
            target_program.intended_entry_term,
            requirement_id,
            category_label.strip().casefold(),
        ]
    )
    return f"course_category_response:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def resolve_course_evidence_for_requirement(
    target_program: TargetProgram,
    requirement: GapPlannedRequirement,
    course_item: GapCourseRequirement,
    canonical_evidence_by_key: Dict[str, UserEvidence],
) -> Optional[UserEvidence]:
    """Resolve one canonical course fact into a non-persistent scoped view."""
    scoped_key = course_requirement_evidence_key(course_item.item_id)
    explicit_scoped = canonical_evidence_by_key.get(scoped_key)
    if explicit_scoped is not None:
        return explicit_scoped

    label = (course_item.canonical_label or course_item.course_name).strip()
    category_candidates = [
        special_course_category_context_key(
            target_program,
            requirement.requirement_id,
            category_label,
        )
        for category_label in dict.fromkeys(
            [label, course_item.course_name.strip()]
        )
        if category_label
    ]
    for category_key in category_candidates:
        if not category_key:
            continue
        category_evidence = canonical_evidence_by_key.get(category_key)
        if category_evidence is not None:
            return category_evidence

    if course_item.prerequisite_kind == "course_category":
        return None
    concrete_key = special_evidence_key("prerequisite_course", label)
    return canonical_evidence_by_key.get(concrete_key)


def runtime_course_evidence_view(
    target_program: TargetProgram,
    requirements: List[GapPlannedRequirement],
    canonical_evidence_by_key: Dict[str, UserEvidence],
) -> Dict[str, UserEvidence]:
    """Materialize requirement-scoped course facts for this evaluation only."""
    runtime = dict(canonical_evidence_by_key)
    for requirement in requirements:
        for course_item in requirement.course_requirements:
            if course_item.authoritative:
                continue
            scoped_key = course_requirement_evidence_key(course_item.item_id)
            if scoped_key in runtime:
                continue
            source = resolve_course_evidence_for_requirement(
                target_program,
                requirement,
                course_item,
                canonical_evidence_by_key,
            )
            if source is None:
                continue
            completed = (
                True
                if source.availability == "known"
                else False
                if source.availability == "known_negative"
                else None
            )
            source_value = source.value if isinstance(source.value, dict) else {}
            runtime[scoped_key] = UserEvidence(
                evidence_type="courses",
                key=scoped_key,
                value={
                    "requirement_id": requirement.requirement_id,
                    "item_id": course_item.item_id,
                    "course_name": course_item.course_name,
                    "completed": completed,
                    "user_course_name": source_value.get("user_course_name"),
                    "matched_user_courses": source_value.get(
                        "matched_user_courses", []
                    ),
                    "derived_from_key": source.key,
                },
                raw_answer=source.raw_answer,
                availability=source.availability,
                updated_at=source.updated_at,
                source_requirement_ids=list(source.source_requirement_ids),
            )
    return runtime


def user_course_evidence_key(course_name: str) -> str:
    return f"user_course:{special_evidence_slug(course_name)}"


def parse_special_targeted_extraction(content: str) -> SpecialTargetedExtractionOutput:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=502,
            detail="Special Requirement extraction returned malformed JSON",
        ) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail="Special Requirement extraction returned an invalid payload",
        )
    groups: List[SpecialPrerequisiteGroupExtraction] = []
    specials: List[SpecialObjectiveRequirementExtraction] = []
    aggregate_credits: List[SpecialAggregateCourseCreditExtraction] = []
    for raw_group in payload.get("prerequisite_groups", []):
        try:
            groups.append(SpecialPrerequisiteGroupExtraction.model_validate(raw_group))
        except ValidationError as error:
            logger.warning(
                "special_interview_malformed_prerequisite_group dropped=true errors=%s",
                error.error_count(),
            )
    for raw_item in payload.get("objective_special_requirements", []):
        try:
            specials.append(SpecialObjectiveRequirementExtraction.model_validate(raw_item))
        except ValidationError as error:
            logger.warning(
                "special_interview_malformed_objective_item dropped=true errors=%s",
                error.error_count(),
            )
    for raw_item in payload.get("aggregate_course_credits", []):
        try:
            aggregate_credits.append(
                SpecialAggregateCourseCreditExtraction.model_validate(raw_item)
            )
        except ValidationError as error:
            logger.warning(
                "special_interview_malformed_aggregate_credit dropped=true errors=%s",
                error.error_count(),
            )
    return SpecialTargetedExtractionOutput(
        prerequisite_groups=groups,
        objective_special_requirements=specials,
        aggregate_course_credits=aggregate_credits,
    )


async def extract_special_requirements_once(
    trusted_requirements: List[Dict[str, Any]],
) -> SpecialTargetedExtractionOutput:
    if not trusted_requirements:
        return SpecialTargetedExtractionOutput()
    schema = SpecialTargetedExtractionOutput.model_json_schema()
    compact_requirements = [
        {
            "requirement_id": item["requirement_id"],
            "category": item["category"],
            "requirement": item["requirement"],
        }
        for item in trusted_requirements
    ]
    prompt = (
        "你是 Special Requirement targeted extractor。只处理输入中的可信 Reviewed "
        "Requirements，不联网，不做 Gap 判断，也不生成任何 question、UI、source_text、"
        "翻译、source_url 或用户是否满足的结论。第一轮 Standard Profile 已覆盖本科院校、"
        "专业、学位/状态、GPA/平均分、IELTS/TOEFL、GRE/GMAT、推荐信、CV、Transcript、"
        "SOP/Personal Statement/Motivation Letter、Portfolio 及其他标准字段；这些绝对不能"
        "输出。只输出两类：A) Requirement 明确列出的 prerequisite course groups；"
        "B) 第一轮未覆盖、官网明确提出、用户可回答客观事实的少量 special requirements。"
        "课程 group relation 只能是 all_of 或 one_of，并严格保留 AND/OR。每个 prerequisite "
        "item 必须输出 prerequisite_kind。明确的具体课程（如 Linear Algebra）输出 "
        "concrete_course + canonical_label；项目定义的课程类别（如 one from the available "
        "Systems courses）输出 course_category + category_label=Systems，绝不能把整句话当作"
        "课程名。只有 Requirement 明确写出数量时才输出 minimum_courses，例如 one from=1、"
        "at least two=2；不得猜测数量。只抽取明确必修课程/类别；example/such as/recommended "
        "不得升级为必修，不得自行补课程。如果 Requirement 用 must include、required courses "
        "are、或 mandatory 语境下的 including 明确逐项点名课程，则每个名称必须分别输出 "
        "concrete_course，relation=all_of；即使同一句还写了 four/three different subjects "
        "或 broad subject area，也绝不能压缩成一个 course_category + minimum_courses。只有"
        "没有逐项列出 mandatory course names 的真正类别要求才使用 course_category。主观的 related "
        "discipline、relevant experience、strong/suitable background 不输出。"
        "如果同一课程 Requirement 明确写出合计课程学分门槛（例如 totalling 22.5 ECTS、"
        "at least 28.5 credits），必须同时输出一个 aggregate_course_credits item："
        "requirement_id 引用当前 Requirement，required_quantity 和 unit 只取原文明示值，"
        "label 简洁描述该 Requirement 的相关课程总学分范围。具体课程与 aggregate total 是"
        "两个独立事实；不得把总学分塞进某一门具体课程，也不得输出每门课程学分。"
        "学费、deadline、"
        "open date、intake、duration、round、行政信息不输出。objective special 的 "
        "expected_answer_type 只允许 ternary；例如明确要求的 certificate、undergraduate "
        "thesis 或其他客观 programme-specific prerequisite。模型只返回 requirement_id、"
        "canonical_label、group relation、special_type、expected_answer_type。requirement_id "
        "必须来自输入。不得判断课程等价性，不得创造官网没有的 Requirement。\n\n"
        f"Reviewed Requirements: {json.dumps(compact_requirements, ensure_ascii=False)}\n"
        f"Output JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n"
        "只输出完整 JSON。"
    )
    raw = await call_deepseek(
        messages=[
            {"role": "system", "content": "只输出严格 JSON；不得调用任何工具。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4_000,
        response_format={"type": "json_object"},
        include_metadata=True,
        diagnostic_label="special_requirement_targeted_extraction",
    )
    result = coerce_deepseek_text_result(raw)
    if not result.content:
        raise HTTPException(
            status_code=502,
            detail="Special Requirement extraction returned an empty response",
        )
    return parse_special_targeted_extraction(result.content)


def explicit_mandatory_course_names(
    requirement_text: str,
    *,
    expected_count: int,
) -> List[str]:
    """Recover an explicit mandatory list when extraction collapsed it to a category.

    This is deliberately narrow: the source must contain a mandatory-list marker and
    the number of independently named courses must exactly match the model-provided
    category count. Examples and recommendations are never promoted.
    """
    text = " ".join(requirement_text.split())
    if expected_count < 2 or re.search(
        r"\b(?:examples?|such as|including but not limited to|recommended)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return []
    marker = re.search(
        r"\b(?:must\s+include|required\s+courses?\s+(?:are|include)|"
        r"(?:must|required)[^.;:]{0,80}\bincluding|including)\b\s*:?\s*",
        text,
        flags=re.IGNORECASE,
    )
    if marker is None:
        return []
    # Bare "including" is accepted only when the same requirement establishes a
    # required/count constraint. This keeps descriptive example lists out.
    marker_text = marker.group(0).casefold()
    if marker_text.strip().startswith("including") and not re.search(
        r"\b(?:must|required|shall|different\s+(?:subjects?|courses?))\b",
        text[: marker.start()],
        flags=re.IGNORECASE,
    ):
        return []
    tail = re.split(r"[.;]", text[marker.end() :], maxsplit=1)[0].strip()
    if not tail:
        return []
    raw_names = re.split(r"\s*,\s*", tail)
    if len(raw_names) == 1 and "/" in tail:
        raw_names = re.split(r"\s*/\s*", tail)
    names: List[str] = []
    for raw_name in raw_names:
        name = re.sub(r"^(?:and|or)\s+", "", raw_name, flags=re.IGNORECASE)
        name = re.sub(
            r"^(?:an?\s+)?(?:in-depth\s+)?course\s+(?:in|on|covering)\s+",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip(" ,:")
        if not name or re.search(r"\b(?:ECTS|credits?|subjects?)\b", name, re.IGNORECASE):
            return []
        names.append(name)
    if len(names) != expected_count or len({name.casefold() for name in names}) != len(names):
        return []
    return names


def normalize_collapsed_named_course_group(
    group: SpecialPrerequisiteGroupExtraction,
    requirement_text: str,
) -> SpecialPrerequisiteGroupExtraction:
    if len(group.courses) != 1:
        return group
    collapsed = group.courses[0]
    if collapsed.prerequisite_kind != "course_category" or collapsed.minimum_courses is None:
        return group
    names = explicit_mandatory_course_names(
        requirement_text,
        expected_count=collapsed.minimum_courses,
    )
    if not names:
        return group
    logger.warning(
        "special_interview_named_courses_expanded requirement_id=%s count=%s",
        group.requirement_id,
        len(names),
    )
    return group.model_copy(
        update={
            "relation": "all_of",
            "courses": [
                SpecialPrerequisiteCourseExtraction(
                    prerequisite_kind="concrete_course",
                    canonical_label=name,
                )
                for name in names
            ],
        }
    )


def build_special_interview_plan_from_extraction(
    request: SpecialInterviewPlanRequest,
    trusted_requirements: List[Dict[str, Any]],
    extraction: SpecialTargetedExtractionOutput,
    *,
    llm_requests: int,
) -> SpecialInterviewPlan:
    sources = {item["requirement_id"]: item for item in trusted_requirements}
    reusable_by_key = {
        canonical_evidence_key(item.key): item.model_copy(
            update={"key": canonical_evidence_key(item.key)}
        )
        for item in request.user_evidence
    }
    groups: List[SpecialInterviewPrerequisiteGroup] = []
    authoritative_groups: List[AuthoritativePrerequisiteGroup] = []
    aggregate_credits: List[SpecialInterviewAggregateCreditItem] = []
    authoritative_credit_items: List[AuthoritativeCourseCreditItem] = []
    seen_groups: Set[tuple[str, str, tuple[str, ...]]] = set()
    extracted_count = 0
    for group in extraction.prerequisite_groups:
        source = sources.get(group.requirement_id)
        if source is None:
            logger.warning(
                "special_interview_unknown_requirement_id requirement_id=%s dropped=true",
                group.requirement_id,
            )
            continue
        group = normalize_collapsed_named_course_group(group, source["requirement"])
        authoritative_items: List[AuthoritativePrerequisiteItem] = []
        seen_item_ids: Set[str] = set()
        for course in group.courses:
            label = course.canonical_label or course.category_label or ""
            item_id = authoritative_prerequisite_item_id(
                group.requirement_id,
                course.prerequisite_kind,
                label,
            )
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            authoritative_items.append(
                AuthoritativePrerequisiteItem(
                    item_id=item_id,
                    prerequisite_kind=course.prerequisite_kind,
                    canonical_label=course.canonical_label,
                    category_label=course.category_label,
                    display_label=label,
                    course_code=(
                        prerequisite_course_code(label)
                        if course.prerequisite_kind == "concrete_course"
                        else None
                    ),
                    minimum_courses=course.minimum_courses,
                    evidence_key=programme_course_evidence_key(
                        request.target_program,
                        group.requirement_id,
                        item_id,
                    ),
                )
            )
        signature = (
            group.requirement_id,
            group.relation,
            tuple(sorted(item.item_id for item in authoritative_items)),
        )
        if not authoritative_items or signature in seen_groups:
            continue
        seen_groups.add(signature)
        group_digest = hashlib.sha256(
            "\n".join(
                [group.requirement_id, group.relation, *signature[2]]
            ).encode("utf-8")
        ).hexdigest()[:16]
        group_id = f"special-prerequisite-{group_digest}"
        authoritative_groups.append(
            AuthoritativePrerequisiteGroup(
                group_id=group_id,
                requirement_id=group.requirement_id,
                relation=group.relation,
                items=authoritative_items,
            )
        )
        extracted_count += len(authoritative_items)
        if group.relation == "one_of" and any(
            reusable_by_key.get(item.evidence_key) is not None
            and reusable_by_key[item.evidence_key].availability == "known"
            for item in authoritative_items
        ):
            continue
        remaining_items = [
            item
            for item in authoritative_items
            if item.evidence_key not in reusable_by_key
        ]
        if not remaining_items:
            continue
        groups.append(
            SpecialInterviewPrerequisiteGroup(
                group_id=group_id,
                relation=group.relation,
                courses=[
                    SpecialInterviewCourseItem(
                        item_id=item.item_id,
                        prerequisite_kind=item.prerequisite_kind,
                        canonical_label=item.canonical_label,
                        category_label=item.category_label,
                        minimum_courses=item.minimum_courses,
                        evidence_key=item.evidence_key,
                        suggested_user_courses=[],
                    )
                    for item in remaining_items
                ],
                source=SpecialInterviewSource(
                    requirement_id=group.requirement_id,
                    requirement=source["requirement"],
                    requirement_zh=source.get("requirement_zh"),
                    source_url=source.get("source_url"),
                    verification_status=source["verification_status"],
                ),
            )
        )

    specials: List[SpecialInterviewObjectiveItem] = []
    seen_special_keys: Set[tuple[str, str]] = set()
    for index, item in enumerate(extraction.objective_special_requirements):
        source = sources.get(item.requirement_id)
        if source is None:
            logger.warning(
                "special_interview_unknown_requirement_id requirement_id=%s dropped=true",
                item.requirement_id,
            )
            continue
        key = special_evidence_key("objective_special", item.canonical_label)
        signature = (item.requirement_id, key)
        if signature in seen_special_keys:
            continue
        seen_special_keys.add(signature)
        extracted_count += 1
        if key in reusable_by_key:
            continue
        specials.append(
            SpecialInterviewObjectiveItem(
                item_id=f"special-objective-{index}",
                canonical_label=item.canonical_label.strip(),
                evidence_key=key,
                special_type=item.special_type.strip(),
                source=SpecialInterviewSource(
                    requirement_id=item.requirement_id,
                    requirement=source["requirement"],
                    requirement_zh=source.get("requirement_zh"),
                    source_url=source.get("source_url"),
                    verification_status=source["verification_status"],
                ),
            )
        )
    seen_credit_items: Set[tuple[str, float, str]] = set()
    for item in extraction.aggregate_course_credits:
        source = sources.get(item.requirement_id)
        if source is None:
            logger.warning(
                "special_interview_unknown_requirement_id requirement_id=%s dropped=true",
                item.requirement_id,
            )
            continue
        signature = (
            item.requirement_id,
            item.required_quantity,
            " ".join(item.unit.casefold().split()),
        )
        if signature in seen_credit_items:
            continue
        seen_credit_items.add(signature)
        item_id = authoritative_course_credit_item_id(
            item.requirement_id,
            item.required_quantity,
            item.unit,
        )
        evidence_key = programme_course_credit_evidence_key(
            request.target_program,
            item.requirement_id,
            item_id,
        )
        authoritative_item = AuthoritativeCourseCreditItem(
            item_id=item_id,
            requirement_id=item.requirement_id,
            label=item.label,
            required_quantity=item.required_quantity,
            unit=item.unit,
            evidence_key=evidence_key,
        )
        authoritative_credit_items.append(authoritative_item)
        extracted_count += 1
        if evidence_key in reusable_by_key:
            continue
        aggregate_credits.append(
            SpecialInterviewAggregateCreditItem(
                **authoritative_item.model_dump(),
                source=SpecialInterviewSource(
                    requirement_id=item.requirement_id,
                    requirement=source["requirement"],
                    requirement_zh=source.get("requirement_zh"),
                    source_url=source.get("source_url"),
                    verification_status=source["verification_status"],
                ),
            )
        )
    remaining_count = (
        sum(len(group.courses) for group in groups)
        + len(specials)
        + len(aggregate_credits)
    )
    return SpecialInterviewPlan(
        target_program=request.target_program,
        prerequisite_groups=groups,
        authoritative_prerequisite_plan=authoritative_groups,
        aggregate_course_credits=aggregate_credits,
        authoritative_course_credit_plan=authoritative_credit_items,
        objective_special_requirements=specials,
        reusable_evidence=list(reusable_by_key.values()),
        trusted_requirement_count=len(trusted_requirements),
        extracted_item_count=extracted_count,
        remaining_item_count=remaining_count,
        extraction_llm_requests=llm_requests,
    )


@app.post(
    "/special-interview/plan",
    response_model=SpecialInterviewPlan,
    tags=["gap"],
)
async def special_interview_plan_endpoint(
    request: SpecialInterviewPlanRequest,
) -> SpecialInterviewPlan:
    """Extract one reusable-fact interview from trusted reviewed requirements."""
    trusted = trusted_reviewed_requirements(request.requirements_review)
    extraction = await extract_special_requirements_once(trusted)
    return build_special_interview_plan_from_extraction(
        request,
        trusted,
        extraction,
        llm_requests=1 if trusted else 0,
    )


@app.post(
    "/special-interview/evidence/submit",
    response_model=SpecialInterviewEvidenceSubmitResponse,
    tags=["gap"],
)
async def special_interview_evidence_submit_endpoint(
    request: SpecialInterviewEvidenceSubmitRequest,
) -> SpecialInterviewEvidenceSubmitResponse:
    """Store typed special-interview facts without parsing or model calls."""
    now = datetime.now(timezone.utc).isoformat()
    evidence: List[UserEvidence] = []
    for answer in request.answers:
        if answer.item_type == "prerequisite_course" and answer.prerequisite_kind is None:
            raise HTTPException(status_code=422, detail="Missing prerequisite kind")
        expected_item_id = (
            authoritative_prerequisite_item_id(
                answer.requirement_id,
                answer.prerequisite_kind,
                answer.canonical_label,
            )
            if answer.item_type == "prerequisite_course"
            and answer.prerequisite_kind is not None
            else None
        )
        if answer.item_type == "aggregate_course_credit":
            expected_item_id = authoritative_course_credit_item_id(
                answer.requirement_id,
                answer.required_quantity or 0,
                answer.unit or "",
            )
        if (
            answer.item_type == "prerequisite_course"
            and answer.item_id != expected_item_id
        ):
            raise HTTPException(status_code=422, detail="Invalid prerequisite item id")
        if (
            answer.item_type == "aggregate_course_credit"
            and answer.item_id != expected_item_id
        ):
            raise HTTPException(status_code=422, detail="Invalid aggregate credit item id")
        if answer.item_type == "prerequisite_course":
            expected_key = programme_course_evidence_key(
                request.target_program,
                answer.requirement_id,
                expected_item_id or "",
            )
        elif answer.item_type == "aggregate_course_credit":
            expected_key = programme_course_credit_evidence_key(
                request.target_program,
                answer.requirement_id,
                expected_item_id or "",
            )
        else:
            expected_key = special_evidence_key(answer.item_type, answer.canonical_label)
        if canonical_evidence_key(answer.evidence_key) != expected_key:
            raise HTTPException(status_code=422, detail="Invalid special evidence key")
        cleaned_course_names = list(
            dict.fromkeys(
                name.strip() for name in answer.user_course_names if name.strip()
            )
        )
        if answer.user_course_name and answer.user_course_name.strip():
            cleaned_course_names = list(
                dict.fromkeys([answer.user_course_name.strip(), *cleaned_course_names])
            )
        if (
            answer.item_type == "prerequisite_course"
            and answer.prerequisite_kind == "course_category"
            and answer.availability == "known"
            and len(cleaned_course_names) < (answer.minimum_courses or 1)
        ):
            raise HTTPException(
                status_code=422,
                detail="Known course category requires the user's actual course names",
            )
        value: Dict[str, Any] = {"canonical_label": answer.canonical_label.strip()}
        if answer.item_type == "prerequisite_course":
            programme_scope = programme_cache_key(
                target_program_cache_identity(request.target_program)
            )
            value.update(
                {
                    "programme_scope": programme_scope,
                    "requirement_id": answer.requirement_id,
                    "item_id": expected_item_id,
                    "prerequisite_kind": answer.prerequisite_kind,
                    "user_course_name": (
                        answer.user_course_name.strip()
                        if answer.user_course_name
                        and answer.prerequisite_kind == "concrete_course"
                        else None
                    ),
                    "category_label": (
                        answer.canonical_label.strip()
                        if answer.prerequisite_kind == "course_category"
                        else None
                    ),
                    "minimum_courses": answer.minimum_courses,
                    "matched_user_courses": (
                        cleaned_course_names
                        if answer.prerequisite_kind == "course_category"
                        else []
                    ),
                    "reusable": False,
                }
            )
        elif answer.item_type == "aggregate_course_credit":
            value = (
                CourseCreditEvidenceValue(
                    requirement_id=answer.requirement_id,
                    label=answer.canonical_label.strip(),
                    quantity=answer.quantity,
                    unit=answer.unit or "",
                ).model_dump()
                if answer.availability == "known"
                else {
                    "requirement_id": answer.requirement_id,
                    "label": answer.canonical_label.strip(),
                    "quantity": None,
                    "unit": answer.unit,
                }
            )
            value.update({
                "item_id": expected_item_id,
                "required_quantity": answer.required_quantity,
                "aggregate_scope": "requirement",
                "reusable": False,
            })
        evidence.append(
            UserEvidence(
                evidence_type=(
                    "prerequisite_course"
                    if answer.item_type == "prerequisite_course"
                    else "courses"
                    if answer.item_type == "aggregate_course_credit"
                    else "generic"
                ),
                key=expected_key,
                value=value,
                raw_answer={
                    "known": "修过" if answer.item_type == "prerequisite_course" else "持有/符合",
                    "known_negative": "没修过" if answer.item_type == "prerequisite_course" else "没有",
                    "unknown": "不确定",
                }[answer.availability]
                if answer.item_type != "aggregate_course_credit"
                else (
                    f"{answer.quantity:g} {answer.unit}"
                    if answer.availability == "known" and answer.quantity is not None
                    else "不确定"
                ),
                availability=answer.availability,
                updated_at=now,
                source_requirement_ids=[answer.requirement_id],
            )
        )
    return SpecialInterviewEvidenceSubmitResponse(evidence=evidence)


async def build_gap_plan(request: GapPlanRequest) -> GapPlan:
    all_formal_requirements = formal_gap_requirements(request.requirements_review)
    formal_requirements = [
        item
        for item in all_formal_requirements
        if item.get("route_scope", "standard") == "standard"
    ]
    excluded_requirements = [
        GapPlannedRequirement(
            requirement_id=item["requirement_id"],
            matchable=False,
            user_matchable=False,
            informational_reason=item.get("excluded_reason") or "",
            category=item["category"],
            requirement=item["requirement"],
            requirement_zh=item.get("requirement_zh"),
            importance=item["importance"],
            requirement_verification_status=item[
                "requirement_verification_status"
            ],
            source_url=item.get("source_url"),
            source_cycle=item.get("source_cycle"),
            temporal_applicability=item["temporal_applicability"],
            temporal_note=item.get("temporal_note"),
            parent_requirement_id=item.get("parent_requirement_id"),
            parent_requirement_text=item.get("parent_requirement_text"),
            parent_has_explicit_conditional_scope=item.get(
                "parent_has_explicit_conditional_scope", False
            ),
            route_scope="special_internal",
            excluded_reason="unsupported_special_internal_route",
            route_scope_source=item.get(
                "route_scope_source", "current_requirement"
            ),
        )
        for item in all_formal_requirements
        if item.get("route_scope") == "special_internal"
    ]
    reusable = merge_reusable_evidence(request.user_profile, request.user_evidence)
    if not formal_requirements:
        return GapPlan(
            target_program=request.target_program,
            requirements=excluded_requirements,
            reusable_evidence=reusable,
            planning_llm_requests=0,
        )

    planner_payload = gap_planner_prompt_payload(
        request,
        formal_requirements,
        reusable,
    )
    output_schema = GapPlannerLLMOutput.model_json_schema()
    prompt = (
        "你是留学申请 Gap Evidence Planner。只根据给定的有效 Requirement 和用户已有证据，"
        "规划一次自适应访谈。不要联网，不得补充、改写或猜测学校要求。\n\n"
        "Requirement provenance 包括 official_verified、user_supplied 和 "
        "model_memory_unverified。后者是兼容字段，代表“AI 参考，当前未确认官方来源”，并不"
        "限定信息只能来自模型训练记忆；它仍可正常规划证据、"
        "确定性/语义匹配和四种 Gap 状态，但相关提问必须明确说“根据目前的 AI 参考信息，"
        "该项目可能要求……”，不得表述为官网事实。\n"
        "只处理输入中的 requirement_id。先判断 Requirement 是否能与用户背景比较。"
        "截止日期、开放时间、处理周期、纯行政说明必须 matchable=false；"
        "资格、成绩、课程、专业、经历、材料要求通常可匹配。\n"
        "match_strategy：明确数值、boolean、数量用 deterministic；专业/课程等价、相关性、"
        "模糊背景用 semantic；相关性加年限/学分等数值用 hybrid。\n"
        "Evidence key 尽量使用可跨项目复用的规范 key：education.university、education.major、"
        "degree_classification、gpa、average_score、ielts、toefl、gre、gmat、courses、experience、"
        "materials.portfolio、materials.cv、materials.transcript、materials.degree_certificate、"
        "materials.recommendations。不要把项目名写入 evidence key。\n"
        "evidence_type 只能从 education_university、education_major、academic_score、"
        "language_score、standardized_score、courses、material_status、material_quantity、"
        "experience、generic 中选择，不得输出其他值。\n"
        "每个 evidence_need 必须输出 value_kind，且只能是 categorical、numeric、boolean、text、"
        "date。value_kind 描述 Evidence 数据语义，不是 UI control_type：degree_classification 固定为"
        "categorical，GPA / average_score 固定为 numeric，材料 availability 固定为 boolean。"
        "不得因为 Requirement 文案改变 canonical datatype，也不得在 value_kind 中输出任何 UI 控件信息。\n"
        "对于 language Requirement 的每个 accepted proof evidence，按原文输出可选 proof_kind："
        "IELTS、TOEFL 等标准化计分考试用 scored_test；English-medium / Medium of Instruction 用"
        "medium_of_instruction；只有原文明示接受特定非考试语言证书或豁免路径时，才分别使用"
        "certificate 或 waiver。不得根据常识新增学校未接受的证明。proof_kind 只描述证明性质，"
        "不得包含 score fields、UI、control_type 或 question text；minimum 和 component threshold"
        "继续放在 constraint 中。\n"
        "constraint.kind 仅允许 score、material_boolean、material_quantity、"
        "experience_duration、course_credit、none。任何 A OR B 替代证据路径都放在同一个"
        "constraint.options（例如 IELTS/TOEFL 或 degree classification/GPA）；"
        "constraint.relation：所有选项都要满足用 all，任一证据路径满足即可用 any。"
        "对于 GRE，evidence key 固定使用 gre；如果原文明示 Verbal、Quantitative 或 "
        "Analytical Writing 的分项门槛，在对应 score option.component 中分别使用 verbal、"
        "quantitative、analytical_writing，并把门槛放在 minimum。不得创建 GRE total score，"
        "不得自动求和或换算。"
        "同一条 Requirement 同时含材料是否具备和数量时，在每个 option.kind 分别填写"
        "material_boolean 或 material_quantity，外层 kind 可用 none。"
        "GPA 与 average_score 必须分别使用自己的 key，禁止换算。"
        "只能解析 Requirement 原文明示的数字、考试替代路径和材料数量：referee/references 的复数"
        "不等于两封；未明确数量的推荐信/支持材料必须按 material_boolean 询问是否已准备，"
        "不能追问或判断具体数量。B2 也不能自行创造 IELTS/TOEFL 分数等价关系。"
        "原文未给阈值时保持 null。"
        "推荐信数量、材料是否准备、考试阈值由代码计算，不能让后续 LLM 做算术。\n"
        "输入若包含 authoritative_prerequisite_plan，该 plan 是 prerequisite item 的唯一权威来源；"
        "你不得为对应 requirement_id 创建、删除、改名或重新拆分 course item，也不得生成新的"
        " item_id。对应 Requirement 的 course_requirements 应保持空数组；Backend 会直接注入"
        " authoritative items。没有 authoritative plan 的旧兼容请求才按下列规则输出"
        " course_requirements。只有原文明示 mandatory / required / must"
        "修读的具体课程或知识项才逐门输出 evidence_key、course_name、canonical_label 和"
        "prerequisite_kind。prerequisite_kind 只能是 concrete_course 或 course_category：明确"
        "具体课程用 concrete_course，项目定义的课程类别/方向用 course_category。可选 group_label 只保存原文"
        "明确的 domain heading，以及原文明示时才填写的 minimum_credits 和 unit。如果 mandatory"
        " Requirement 先列出领域，再在括号中穷举该领域所需的具体 introductory topics（例如"
        "Domain (item A, item B, item C)），括号内每个 item 都是独立 required course_requirement，"
        "不是 domain alternatives；必须保留全部 item，外层 relation 使用 all，不得压缩为"
        "courses.domain generic evidence、multi_select 或 min_selections=1。仅当原文使用 examples、"
        "such as、including but not limited to、recommended 等非穷举/非强制措辞时，括号或列表项"
        "课程不得自动变成 required，也不得自行补 prerequisite。具体 required courses 与总学分"
        "threshold 是两个独立事实：总量继续放在 course_credit constraint；如果只写某领域共"
        "22.5 ECTS 而没有明确课程清单，course_requirements 必须是空数组。"
        "course_requirements 不得包含 UI、checklist 或 question text。\n"
        "输入若包含 authoritative_course_credit_plan，其中的 requirement-scoped evidence_key、"
        "required_quantity 和 unit 是 aggregate course-credit 的权威结构；不得改成全局"
        "courses.total_credits，也不得把一个 Requirement 的总学分 key 用于另一个 Requirement。"
        "Backend 会注入并校验该 course_credit constraint；模型不得创建重复 aggregate item。\n"
        "每条 Requirement 还必须输出 conditional metadata：is_conditional、condition_text、"
        "controlling_evidence_keys、predicate_relation、predicates。只有原文明示 if selecting、"
        "applicants from、where applicable、"
        "only for applicants with 等适用条件时，is_conditional=true，并保留原文中的明确条件描述；"
        "条件能可靠映射到本 Requirement 已有 canonical evidence 时才填写 controlling keys，否则"
        "保持空数组。每个 predicate 的 evidence_key 必须逐字引用 controlling_evidence_keys 中的"
        "合法 key；operator 只能是 equals 或 in；expected_values 必须是非空数组，且值只能来自"
        "Requirement 原文明示的条件取值。equals 只输出一个 expected value，in 可输出原文明示的"
        "多个可接受值。多个 predicate 全部成立才适用时 predicate_relation=all，任一成立即可时"
        "使用 any。不得凭常识补充同义词、缩写或其他取值；无法可靠提取 predicate 时必须输出"
        "predicates=[]，由 backend 保持 pending。不得根据常识创造条件，也不得把 recommendation / "
        "preference 自动当作 conditional。只描述条件与 predicate，不判断其当前"
        "active/inactive/pending 状态，不生成 UI、question 或 control metadata。\n"
        "Conditional metadata 必须严格限定在当前 requirement_id 和当前 Requirement 原文本身。"
        "不得因为同一网页段落、同一 source、邻近 Requirement 或同一 pathway section，把某条"
        "Requirement 的条件传播给另一条普通 Requirement。普通 Requirement 自身没有 pathway /"
        " applicant 限定时必须 is_conditional=false，即使附近存在 Accelerated 或其他专属路径。"
        "若 general Requirement 与 pathway-specific Requirement 内容相似，也必须分别保留各自的"
        "applicability scope，不得合并或复制 conditional metadata。controlling_evidence_keys 必须"
        "真正用于判断当前 Requirement 是否适用；仅仅提到某所本科院校、学历或年级，不得自动使用"
        "education.university / education.degree 作为 controller。\n"
        "Conditional applicability 与 eligibility 必须分开：controller 只回答该 Requirement 是否适用；"
        "进入适用范围后才判断用户是否满足资格。对于 pathway-specific Requirement，用户是否选择该"
        "pathway 是 applicability；院校、年级、advisor 等通常是该 pathway 内的 eligibility evidence，"
        "不得直接替代 pathway selection predicate。若原文明示一个可用 yes/no 表达的 applicability"
        "事实，可以为同一 Requirement 声明 requirement-scoped generic boolean evidence_need，"
        "predicate 使用 equals + expected_values=[\"true\"]，并提供 boolean other descriptor。"
        "这不是新增 canonical key；key 仍必须属于当前 Requirement，且不得从常识创造条件。\n"
        "如果 Planner Input 明确给出 inherits_parent_applicability=true、parent_requirement_id 和"
        "parent_requirement_text，当前 Requirement 是由 backend 从该 parent 拆出的 synthetic child；"
        "此时必须继承 parent 原文明示的 applicability scope，并为 child 保留与 parent 一致的"
        "structured conditional metadata。只有这种显式 parent-child provenance 允许继承；不得从"
        "相邻 Requirement、相同 source URL、相似文本或 section 关键词推断继承。\n"
        "对于无法归入已支持领域的 programme-specific Requirement，可在该 Requirement 的"
        "other_items 中输出受限 Evidence descriptor。每项只能包含 source_evidence_key、label、"
        "value_kind、options；source_evidence_key 必须逐字引用同一 Requirement 已声明的"
        "evidence_need key。value_kind 只能是 boolean、numeric、single_select、multi_select、"
        "short_text。single_select/multi_select 的 options 只能逐项提取 Requirement 原文明示的"
        "有限选项；multi_select 仅在原文明示可多选时使用。其他 kind 的 options 必须为空。"
        "other_items 不得包含 control_type、fields、value_path、validation、UI layout、question text"
        "或自定义 value shape。成功输出 other_item 后不得再为同一 source evidence 输出 question；"
        "由 backend 生成控件。Conditional controller 优先只使用 boolean、single_select、multi_select；"
        "不得为了 controller 发明原文不存在的 selector options，也不得发明 canonical evidence key。"
        "conditional controller 无法可靠映射时保持 other_items=[]，由 backend 保持 pending，且不得为"
        "该 controller 输出 legacy question；普通非 controller evidence 无法映射时仍可继续旧 questions 路径；"
        "不得为了覆盖率创造 descriptor。\n"
        "所有面向用户的 question 必须使用简洁自然的中文。问题应合并相关 Evidence，"
        "例如一次询问所有相关课程，不要逐门课程机械提问。"
        "已有 evidence 的 availability 无论 known、known_negative 还是 unknown，都代表已经回答，"
        "不得重复提问。不允许为 informational Requirement 生成问题。\n\n"
        "每个 question 同时输出可渲染的 UI schema。prompt 是面向用户的问题；"
        "每个 question 必须填写它所属的 requirement_id，并且只能包含该 Requirement 内定义的"
        "evidence keys。即使两个 Requirement 的 category 相同，也不得合并成同一 question；"
        "ANY/ALL 只能作用于同一个 requirement_id 内的 alternatives。"
        "backend 提供的 evidence_needs 是该 Requirement/evidence group 唯一合法的 canonical key 集。"
        "expected_evidence_keys、options[].evidence_key 和 fields[].evidence_key 只能逐字引用其中的 key，"
        "不得创建新的 namespace 或 key；backend 会在返回前覆盖 allowed_evidence_keys 并校验。"
        "group_relation 使用 any/all；"
        "control_type 只能是 boolean、single_select、multi_select、number、number_group、date，"
        "正常主路径禁止 text_fallback。options 和 fields 必须从 Requirement 原文及其 evidence_needs 动态产生，"
        "不得引入 Requirement 没有的新门槛。field.evidence_key 必须属于 expected_evidence_keys；"
        "field.value_path 只能使用 schema 枚举。single_select/multi_select 的每个 option 必须有"
        "稳定 value 和用户可读 label；如 option 对应某一 ANY branch，填写 evidence_key。"
        "boolean/number/date 至少提供一个 field；number_group 为所有实际缺失数值字段提供 fields；"
        "对于 all group，所有当前缺失 slot 都必须有可提交控件；对于 any group，至少一个完整合法"
        "branch 必须可提交。如果无法可靠结构化，也必须返回最接近的 structured schema 供 backend"
        "校验和窄修复，不得自行输出 text_fallback。unknown / negative terminal actions 由系统"
        "统一提供和处理，不能依赖 options，也不得为它们发明 evidence key。allow_other 表示"
        "用户可选择补充自由文本。UI 选项必须由当前 Requirement 动态生成，不能套用固定学校或"
        "固定考试答案。\n\n"
        "当同一 language Requirement 的 any group 提供多种语言证明路径时，第一问只生成"
        "single_select selector：每个 accepted proof branch 一个 option，fields 必须为空。"
        "不得在该题同时生成 IELTS/TOEFL score fields 或非考试证明 field；用户选择考试后由代码"
        "生成确定性的成绩表。非考试证明 option 只能使用其 canonical evidence key 和合法"
        "evidence_value，不得发明 status 等 value_path。\n\n"
        "Temporal applicability 只限制后续硬性 Gap 结论，不应阻止收集可复用的用户事实。"
        "对于 previous_cycle 或 unknown 的 Requirement，如果学历、专业、成绩、语言、课程、"
        "经历或材料状态仍可向用户收集，保持 matchable=true，并正常输出 evidence_needs 和"
        "问题；backend 会在 Gap adjudication 时阻止硬性 not_met。not_yet_published 不生成"
        "证据问题。\n\n"
        f"Planner Input：{json.dumps(planner_payload, ensure_ascii=False)}\n"
        f"输出 JSON Schema：{json.dumps(output_schema, ensure_ascii=False)}\n"
        "只输出 JSON，不要解释。"
    )
    messages = [
        {"role": "system", "content": "你只输出严格符合 schema 的 JSON，不使用任何工具。"},
        {"role": "user", "content": prompt},
    ]
    allowed_requirement_ids = {
        item["requirement_id"] for item in formal_requirements
    }
    parsed_output: Optional[GapPlannerLLMOutput] = None
    for attempt in range(2):
        output_budget = (
            GAP_PLANNER_INITIAL_MAX_OUTPUT_TOKENS
            if attempt == 0
            else GAP_PLANNER_RETRY_MAX_OUTPUT_TOKENS
        )
        attempt_messages = list(messages)
        if attempt:
            attempt_messages.append(
                {
                    "role": "system",
                    "content": (
                        "上一次输出未形成完整合法 JSON。使用完全相同的 Planner Input，"
                        "立即返回一份完整、合法、符合 schema 的 JSON；不要解释或省略闭合符号。"
                    ),
                }
            )
        try:
            raw_result = await call_deepseek(
                messages=attempt_messages,
                max_tokens=output_budget,
                response_format={"type": "json_object"},
                include_metadata=True,
                diagnostic_label=f"gap_planner attempt={attempt + 1}",
            )
        except HTTPException:
            for formal in formal_requirements:
                log_question_generation_diagnostics(
                    "initial_generation_failed",
                    GapQuestionGenerationDiagnostics(
                        requirement_id=formal["requirement_id"],
                        initial_failure_stage="initial_generation_failed",
                        initial_validator_error="gap_planner_request_failed",
                        final_failure_stage="initial_generation_failed",
                    ),
                )
            raise
        result = coerce_deepseek_text_result(raw_result)
        try:
            parsed_output = parse_gap_planner_output(result)
            validate_gap_planner_business_output(
                parsed_output,
                allowed_requirement_ids,
            )
            break
        except GapPlannerOutputError as error:
            if error.kind in {"generation_incomplete", "malformed_json"} and attempt == 0:
                logger.warning(
                    "gap_planner_narrow_retry kind=%s next_attempt=2 output_budget=%d",
                    error.kind,
                    GAP_PLANNER_RETRY_MAX_OUTPUT_TOKENS,
                )
                continue
            logger.error(
                "gap_planner_failed kind=%s attempts=%d",
                error.kind,
                attempt + 1,
            )
            for formal in formal_requirements:
                log_question_generation_diagnostics(
                    "initial_generation_failed",
                    GapQuestionGenerationDiagnostics(
                        requirement_id=formal["requirement_id"],
                        initial_failure_stage="initial_generation_failed",
                        initial_validator_error=error.kind,
                        final_failure_stage="initial_generation_failed",
                    ),
                )
            raise HTTPException(
                status_code=502,
                detail="Gap Planner failed to produce a valid structured result",
            ) from error
    if parsed_output is None:
        raise HTTPException(
            status_code=502,
            detail="Gap Planner failed to produce a valid structured result",
        )
    draft = materialize_gap_planner_output(parsed_output)

    formal_by_id = {item["requirement_id"]: item for item in formal_requirements}
    draft_by_id = {
        item.requirement_id: item
        for item in draft.requirements
        if item.requirement_id in formal_by_id
    }
    reusable_by_key = {canonical_evidence_key(item.key): item for item in reusable}
    material_owner_count: Dict[str, int] = {}
    for draft_item in draft_by_id.values():
        for draft_need in draft_item.evidence_needs:
            original_key = canonical_evidence_key(draft_need.key)
            if standard_material_definition(original_key) is not None:
                material_owner_count[original_key] = (
                    material_owner_count.get(original_key, 0) + 1
                )
    planned: List[GapPlannedRequirement] = []
    needs_by_key: Dict[str, GapEvidenceNeed] = {}
    for requirement_id, formal in formal_by_id.items():
        item = draft_by_id.get(requirement_id)
        if item is None:
            item = GapPlannerRequirementDraft(
                requirement_id=requirement_id,
                matchable=True,
                match_strategy="semantic",
                evidence_needs=[
                    GapEvidenceNeed(
                        key=f"generic.{requirement_id}",
                        evidence_type="generic",
                        label="与该要求相关的个人背景",
                    )
                ],
            )
        conditional_scope_source: Literal["none", "self", "parent"] = "none"
        conditional_scope_text = formal["requirement"]
        if formal.get("inherits_parent_applicability"):
            conditional_scope_text = (
                formal.get("parent_requirement_text") or formal["requirement"]
            )
            parent_scope_item = draft_by_id.get(
                formal.get("parent_scope_requirement_id", "")
            )
            inherited_conditional = (
                parent_scope_item.conditional
                if parent_scope_item and parent_scope_item.conditional.is_conditional
                else item.conditional
                if item.conditional.is_conditional
                else None
            )
            if inherited_conditional is not None:
                controller_keys = {
                    canonical_evidence_key(key)
                    for key in inherited_conditional.controlling_evidence_keys
                }
                parent_needs = (
                    parent_scope_item.evidence_needs if parent_scope_item else []
                )
                merged_needs = list(item.evidence_needs)
                for parent_need in parent_needs:
                    if (
                        canonical_evidence_key(parent_need.key) in controller_keys
                        and all(
                            canonical_evidence_key(existing.key)
                            != canonical_evidence_key(parent_need.key)
                            for existing in merged_needs
                        )
                    ):
                        merged_needs.append(parent_need)
                inherited_other_items = list(item.other_items)
                if parent_scope_item:
                    for descriptor in parent_scope_item.other_items:
                        if (
                            canonical_evidence_key(descriptor.source_evidence_key)
                            in controller_keys
                            and all(
                                canonical_evidence_key(existing.source_evidence_key)
                                != canonical_evidence_key(descriptor.source_evidence_key)
                                for existing in inherited_other_items
                            )
                        ):
                            inherited_other_items.append(descriptor)
                item = item.model_copy(
                    update={
                        "conditional": inherited_conditional,
                        "evidence_needs": merged_needs,
                        "other_items": inherited_other_items,
                    }
                )
                conditional_scope_source = "parent"
        elif item.conditional.is_conditional:
            conditional_scope_source = "self"
        temporally_matchable = requirement_is_temporally_matchable(
            formal["temporal_applicability"]
        )
        collects_evidence = requirement_allows_evidence_collection(
            formal["temporal_applicability"]
        )
        deterministically_informational = formal.get("gap_eligibility") != "matchable"
        user_matchable = item.matchable and not deterministically_informational
        material_policy_by_key: Dict[
            str, tuple[str, StandardMaterialType, str, bool]
        ] = {}
        if formal["category"] == "materials":
            for need in item.evidence_needs:
                definition = standard_material_definition(need.key)
                if definition is None:
                    continue
                material_type, default_label = definition
                is_recommendation_quantity = material_type == "recommendation_letters"
                if need.evidence_type not in {"material_status", "material_quantity"}:
                    continue
                if need.evidence_type == "material_quantity" and not is_recommendation_quantity:
                    continue
                item_id = material_policy_item_id(requirement_id, material_type)
                scoped_key = material_policy_evidence_key(
                    item_id,
                    quantity=is_recommendation_quantity,
                )
                material_policy_by_key[canonical_evidence_key(need.key)] = (
                    scoped_key,
                    material_type,
                    item_id,
                    is_recommendation_quantity,
                )
        normalized_constraint = item.constraint.model_copy(
            update={
                "options": [
                    option.model_copy(
                        update={
                            "key": (
                                "experience"
                                if formal["category"] == "experience"
                                else material_policy_by_key.get(
                                    canonical_evidence_key(option.key),
                                    (canonical_evidence_key(option.key), "cv", ""),
                                )[0]
                            ),
                            "kind": (
                                "material_quantity"
                                if (
                                    material_policy_by_key.get(
                                        canonical_evidence_key(option.key)
                                    )
                                    and material_policy_by_key[
                                        canonical_evidence_key(option.key)
                                    ][3]
                                )
                                else option.kind
                            ),
                            "required_quantity": (
                                option.required_quantity
                                if option.required_quantity is not None
                                else 1
                                if (
                                    material_policy_by_key.get(
                                        canonical_evidence_key(option.key)
                                    )
                                    and material_policy_by_key[
                                        canonical_evidence_key(option.key)
                                    ][3]
                                    and (option.kind or item.constraint.kind)
                                    == "material_boolean"
                                )
                                else None
                            ),
                            "unit": (
                                option.unit
                                or (
                                    "recommenders"
                                    if (
                                        material_policy_by_key.get(
                                            canonical_evidence_key(option.key)
                                        )
                                        and material_policy_by_key[
                                            canonical_evidence_key(option.key)
                                        ][3]
                                    )
                                    else ""
                                )
                            ),
                        }
                    )
                    for option in item.constraint.options
                ]
            }
        )
        normalized_needs = []
        for need in item.evidence_needs:
            original_canonical_key = (
                "experience"
                if need.evidence_type == "experience"
                else canonical_evidence_key(need.key)
            )
            material_policy = material_policy_by_key.get(original_canonical_key)
            canonical_key = (
                material_policy[0] if material_policy else original_canonical_key
            )
            if material_policy and canonical_key not in reusable_by_key:
                legacy_item = reusable_by_key.get(original_canonical_key)
                if legacy_item and (
                    material_owner_count.get(original_canonical_key) == 1
                    or requirement_id in legacy_item.source_requirement_ids
                ):
                    reusable_by_key[canonical_key] = legacy_item.model_copy(
                        update={"key": canonical_key}
                    )
            matching_option = next(
                (
                    option
                    for option in normalized_constraint.options
                    if canonical_evidence_key(option.key) == canonical_key
                ),
                None,
            )
            canonical_need = need.model_copy(update={"key": canonical_key})
            normalized_evidence_type: GapEvidenceType = (
                "material_quantity"
                if material_policy and material_policy[3]
                else need.evidence_type
            )
            final_value_kind = (
                "numeric"
                if need.evidence_type == "courses"
                and matching_option
                and (matching_option.kind or normalized_constraint.kind)
                == "course_credit"
                else validated_evidence_value_kind(
                    canonical_key,
                    normalized_evidence_type,
                    need.value_kind,
                )
            )
            final_proof_kind = validated_language_proof_kind(
                canonical_key,
                need.proof_kind,
            )
            normalized = need.model_copy(
                update={
                    "key": canonical_key,
                    "evidence_type": normalized_evidence_type,
                    "value_kind": final_value_kind,
                    "proof_kind": final_proof_kind,
                    "required_fields": required_fields_for_evidence_need(
                        canonical_need.model_copy(
                            update={"evidence_type": normalized_evidence_type}
                        ),
                        normalized_constraint,
                    ),
                    "evidence_group": (
                        f"{requirement_id}:alternatives"
                        if normalized_constraint.relation == "any"
                        else requirement_id
                    ),
                    "group_relation": normalized_constraint.relation,
                    "minimum": matching_option.minimum if matching_option else None,
                    "component_minimum": (
                        matching_option.component_minimum if matching_option else None
                    ),
                    "required_quantity": (
                        matching_option.required_quantity if matching_option else None
                    ),
                    "unit": matching_option.unit if matching_option else None,
                    "material_type": material_policy[1] if material_policy else None,
                    "item_id": material_policy[2] if material_policy else None,
                    "label": (
                        need.label
                        or (
                            STANDARD_MATERIAL_KEYS[original_canonical_key][1]
                            if material_policy
                            else ""
                        )
                    ),
                }
            )
            reusable_item = reusable_by_key.get(canonical_key)
            normalized.already_known = bool(
                reusable_item
                and evidence_is_terminal_for_need(normalized, reusable_item)
            )
            if all(existing.key != canonical_key for existing in normalized_needs):
                normalized_needs.append(normalized)
        has_authoritative_course_plan = any(
            group.requirement_id == requirement_id
            for group in request.authoritative_prerequisite_plan
        )
        authoritative_credit_items = authoritative_gap_course_credit_items(
            request.target_program,
            requirement_id,
            request.authoritative_course_credit_plan,
        )
        has_authoritative_credit_plan = bool(authoritative_credit_items)
        if has_authoritative_course_plan:
            if item.course_requirements:
                logger.warning(
                    "gap_planner_course_items_ignored requirement_id=%s count=%d authority=backend",
                    requirement_id,
                    len(item.course_requirements),
                )
            normalized_course_requirements = authoritative_gap_course_requirements(
                request.target_program,
                requirement_id,
                request.authoritative_prerequisite_plan,
            )
            authoritative_credit_options = (
                [
                    GapConstraintOption(
                        key=credit_item.evidence_key,
                        kind="course_credit",
                        required_quantity=credit_item.required_quantity,
                        unit=credit_item.unit,
                    )
                    for credit_item in authoritative_credit_items
                ]
                if has_authoritative_credit_plan
                else [
                    option
                    for option in normalized_constraint.options
                    if (option.kind or normalized_constraint.kind) == "course_credit"
                ]
            )
            normalized_constraint = normalized_constraint.model_copy(
                update={
                    "kind": (
                        "course_credit" if authoritative_credit_options else "none"
                    ),
                    "options": authoritative_credit_options,
                    "relation": (
                        "any"
                        if not authoritative_credit_options
                        and normalized_course_requirements
                        and {
                            course.group_relation
                            for course in normalized_course_requirements
                        }
                        == {"one_of"}
                        else "all"
                    ),
                }
            )
        else:
            normalized_course_requirements = normalize_course_requirements(
                requirement_id,
                item.course_requirements,
                normalized_needs,
            )
            if has_authoritative_credit_plan:
                non_credit_options = [
                    option
                    for option in normalized_constraint.options
                    if (option.kind or normalized_constraint.kind) != "course_credit"
                ]
                authoritative_credit_options = [
                    GapConstraintOption(
                        key=credit_item.evidence_key,
                        kind="course_credit",
                        required_quantity=credit_item.required_quantity,
                        unit=credit_item.unit,
                    )
                    for credit_item in authoritative_credit_items
                ]
                all_options = [*non_credit_options, *authoritative_credit_options]
                normalized_constraint = normalized_constraint.model_copy(
                    update={
                        "kind": (
                            "course_credit"
                            if all_options and not non_credit_options
                            else "none"
                        ),
                        "options": all_options,
                        "relation": "all",
                    }
                )
        course_item_source_keys = {
            course_item.evidence_key
            for course_item in normalized_course_requirements
        }
        course_credit_keys = {
            canonical_evidence_key(option.key)
            for option in normalized_constraint.options
            if (option.kind or normalized_constraint.kind) == "course_credit"
            and option.required_quantity is not None
        }
        normalized_needs = [
            need
            for need in normalized_needs
            if (
                (
                    not (has_authoritative_course_plan or has_authoritative_credit_plan)
                    and need.key not in course_item_source_keys
                )
                or need.key in course_credit_keys
                or need.evidence_type != "courses"
            )
        ]
        for credit_item in authoritative_credit_items:
            credit_need = GapEvidenceNeed(
                key=credit_item.evidence_key,
                evidence_type="courses",
                value_kind="numeric",
                label=credit_item.label,
                required_fields=["quantity"],
                evidence_group=requirement_id,
                group_relation="all",
                required_quantity=credit_item.required_quantity,
                unit=credit_item.unit,
            )
            reusable_credit = reusable_by_key.get(credit_need.key)
            credit_need.already_known = bool(
                reusable_credit
                and evidence_is_terminal_for_need(credit_need, reusable_credit)
            )
            if all(need.key != credit_need.key for need in normalized_needs):
                normalized_needs.append(credit_need)
        for course_item in normalized_course_requirements:
            course_item_label = (
                f"{course_item.group_label} — {course_item.course_name}"
                if course_item.group_label
                else course_item.course_name
            )
            item_need = GapEvidenceNeed(
                key=gap_course_item_evidence_key(course_item),
                evidence_type="courses",
                value_kind="boolean",
                label=course_item_label,
                required_fields=["completed"],
                evidence_group=requirement_id,
                group_relation=(
                    "any" if course_item.group_relation == "one_of" else "all"
                ),
            )
            reusable_item = reusable_by_key.get(item_need.key)
            item_need.already_known = bool(
                reusable_item
                and evidence_is_terminal_for_need(item_need, reusable_item)
            )
            normalized_needs.append(item_need)
            if course_item.minimum_credits is not None and course_item.unit:
                credit_need = GapEvidenceNeed(
                    key=course_requirement_credit_evidence_key(course_item.item_id),
                    evidence_type="courses",
                    value_kind="numeric",
                    label=course_item_label,
                    required_fields=["quantity"],
                    evidence_group=requirement_id,
                    group_relation="all",
                    required_quantity=course_item.minimum_credits,
                    unit=course_item.unit,
                )
                reusable_credit = reusable_by_key.get(credit_need.key)
                credit_need.already_known = bool(
                    reusable_credit
                    and evidence_is_terminal_for_need(credit_need, reusable_credit)
                )
                normalized_needs.append(credit_need)
        normalized_other_items = normalize_other_descriptors(
            requirement_id,
            conditional_scope_text,
            item.other_items,
            normalized_needs,
        )
        other_key_map = {
            other_item.source_evidence_key: other_item.evidence_key
            for other_item in normalized_other_items
        }
        if other_key_map:
            normalized_constraint = normalized_constraint.model_copy(
                update={
                    "options": [
                        option.model_copy(
                            update={
                                "key": other_key_map.get(option.key, option.key)
                            }
                        )
                        for option in normalized_constraint.options
                    ]
                }
            )
            normalized_needs = [
                need for need in normalized_needs if need.key not in other_key_map
            ]
            for other_item in normalized_other_items:
                required_field = {
                    "boolean": "status",
                    "numeric": "quantity",
                    "single_select": "description",
                    "multi_select": "description",
                    "short_text": "description",
                }[other_item.value_kind]
                normalized_need = GapEvidenceNeed(
                    key=other_item.evidence_key,
                    evidence_type="generic",
                    value_kind=(
                        "boolean"
                        if other_item.value_kind == "boolean"
                        else "numeric"
                        if other_item.value_kind == "numeric"
                        else "categorical"
                        if other_item.value_kind in {"single_select", "multi_select"}
                        else "text"
                    ),
                    label=other_item.label,
                    required_fields=[required_field],
                    evidence_group=requirement_id,
                    group_relation=normalized_constraint.relation,
                    item_id=other_item.item_id,
                    other_value_kind=other_item.value_kind,
                    other_options=other_item.options,
                )
                existing_other = reusable_by_key.get(normalized_need.key)
                normalized_need.already_known = bool(
                    existing_other
                    and evidence_is_terminal_for_need(
                        normalized_need, existing_other
                    )
                )
                normalized_needs.append(normalized_need)
        conditional_metadata = item.conditional.model_copy(
            update={
                "controlling_evidence_keys": [
                    other_key_map.get(
                        canonical_evidence_key(key),
                        material_policy_by_key.get(
                            canonical_evidence_key(key),
                            (canonical_evidence_key(key), "cv", "", False),
                        )[0],
                    )
                    for key in item.conditional.controlling_evidence_keys
                ],
                "predicates": [
                    predicate.model_copy(
                        update={
                            "evidence_key": other_key_map.get(
                                canonical_evidence_key(predicate.evidence_key),
                                material_policy_by_key.get(
                                    canonical_evidence_key(predicate.evidence_key),
                                    (
                                        canonical_evidence_key(predicate.evidence_key),
                                        "cv",
                                        "",
                                        False,
                                    ),
                                )[0],
                            )
                        }
                    )
                    for predicate in item.conditional.predicates
                ],
            }
        )
        normalized_conditional = normalize_conditional_metadata(
            requirement_id,
            conditional_scope_text,
            conditional_metadata,
            normalized_needs,
        )
        if not normalized_conditional.is_conditional:
            conditional_scope_source = "none"
        match_strategy = item.match_strategy
        option_kinds = {option.kind for option in normalized_constraint.options if option.kind}
        if formal["category"] == "materials" and (
            normalized_constraint.kind in {"material_boolean", "material_quantity"}
            or option_kinds
            and option_kinds <= {"material_boolean", "material_quantity"}
        ):
            match_strategy = "deterministic"
        elif formal["category"] in {
            "academic", "language", "standardized_test"
        } and normalized_constraint.kind == "score":
            match_strategy = "deterministic"
        elif formal["category"] == "course" and (
            normalized_course_requirements
            or normalized_constraint.kind == "course_credit"
            or "course_credit" in option_kinds
        ):
            match_strategy = "deterministic"
        planned.append(
            GapPlannedRequirement(
                **formal,
                user_matchable=user_matchable,
                matchable=user_matchable and temporally_matchable,
                informational_reason=(
                    (
                        formal.get("gap_eligibility", "")
                        if deterministically_informational
                        else item.informational_reason
                    )
                    if temporally_matchable
                    else temporal_gap_explanation(
                        formal["temporal_applicability"],
                        formal["source_cycle"],
                        formal["temporal_note"],
                    )[1]
                ),
                match_strategy=match_strategy,
                evidence_needs=(
                    normalized_needs
                    if user_matchable and collects_evidence
                    else []
                ),
                constraint=(
                    normalized_constraint
                    if user_matchable and collects_evidence
                    else GapDeterministicConstraint()
                ),
                course_requirements=(
                    normalized_course_requirements
                    if user_matchable and collects_evidence
                    else []
                ),
                conditional=normalized_conditional,
                conditional_scope_source=conditional_scope_source,
                other_items=(
                    normalized_other_items
                    if user_matchable and collects_evidence
                    else []
                ),
            )
        )

    runtime_reusable_by_key = runtime_course_evidence_view(
        request.target_program,
        planned,
        reusable_by_key,
    )
    planned = [
        item.model_copy(
            update={
                "evidence_needs": [
                    need.model_copy(
                        update={
                            "already_known": bool(
                                (existing := runtime_reusable_by_key.get(need.key))
                                and evidence_is_terminal_for_need(need, existing)
                            )
                        }
                    )
                    for need in item.evidence_needs
                ]
            }
        )
        for item in planned
    ]
    planned = [
        item.model_copy(
            update={
                "conditional_state": resolve_conditional_state(
                    item, runtime_reusable_by_key
                )
            }
        )
        for item in planned
    ]
    question_policy_requirements = conditional_question_policy_view(planned)
    conditional_controller_keys_by_requirement = {
        item.requirement_id: {
            canonical_evidence_key(key)
            for key in item.conditional.controlling_evidence_keys
        }
        for item in question_policy_requirements
        if item.conditional_state == "pending"
    }
    needs_by_requirement = {
        item.requirement_id: {need.key: need for need in item.evidence_needs}
        for item in question_policy_requirements
    }
    requirement_ids_by_key: Dict[str, List[str]] = {}
    for item in question_policy_requirements:
        for need in item.evidence_needs:
            requirement_ids_by_key.setdefault(need.key, []).append(
                item.requirement_id
            )
    requirement_order = {
        item.requirement_id: index
        for index, item in enumerate(question_policy_requirements)
    }

    questions, covered_missing_keys = build_backend_academic_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    language_questions, language_covered_keys = build_backend_language_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(language_questions)
    covered_missing_keys.update(language_covered_keys)
    course_questions, course_covered_keys = build_backend_course_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(course_questions)
    covered_missing_keys.update(course_covered_keys)
    gre_questions, gre_covered_keys = build_backend_gre_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(gre_questions)
    covered_missing_keys.update(gre_covered_keys)
    experience_questions, experience_covered_keys = build_backend_experience_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(experience_questions)
    covered_missing_keys.update(experience_covered_keys)
    material_questions, material_covered_keys = build_backend_material_questions(
        question_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(material_questions)
    covered_missing_keys.update(material_covered_keys)
    controller_questions, controller_covered_keys = (
        build_backend_conditional_controller_questions(
            question_policy_requirements,
            runtime_reusable_by_key,
            covered_missing_keys,
        )
    )
    questions.extend(controller_questions)
    covered_missing_keys.update(controller_covered_keys)
    other_policy_requirements = [
        item.model_copy(
            update={
                "other_items": [
                    other_item
                    for other_item in item.other_items
                    if other_item.evidence_key not in controller_covered_keys
                ]
            }
        )
        for item in question_policy_requirements
    ]
    other_questions, other_covered_keys = build_backend_other_questions(
        other_policy_requirements,
        runtime_reusable_by_key,
    )
    questions.extend(other_questions)
    covered_missing_keys.update(other_covered_keys)
    reusable_any_groups: Dict[str, List[GapEvidenceNeed]] = {}
    needs_by_group: Dict[str, List[GapEvidenceNeed]] = {}
    for item in question_policy_requirements:
        for need in item.evidence_needs:
            if need.evidence_group:
                needs_by_group.setdefault(need.evidence_group, []).append(need)
            if need.evidence_group and need.group_relation == "any":
                reusable_any_groups.setdefault(need.evidence_group, []).append(need)
    satisfied_reusable_groups = {
        group
        for group, needs in reusable_any_groups.items()
        if any(
            evidence_satisfies_need(
                need, runtime_reusable_by_key[need.key.casefold()]
            )
            for need in needs
            if need.key.casefold() in runtime_reusable_by_key
        )
    }
    ai_reference_keys = {
        need.key.casefold()
        for item in question_policy_requirements
        if item.requirement_verification_status == "model_memory_unverified"
        for need in item.evidence_needs
    }
    def append_owned_question(
        question: GapPlannerQuestion,
        question_requirement_id: str,
        base_keys: List[str],
        *,
        reconstructed: bool,
    ) -> None:
        question_needs_by_key = needs_by_requirement[question_requirement_id]
        authoritative_keys = [
            key for key in base_keys if key in question_needs_by_key
        ]
        referenced_groups = {
            question_needs_by_key[key].evidence_group
            for key in authoritative_keys
            if key in question_needs_by_key
            and question_needs_by_key[key].evidence_group
        }
        for group in referenced_groups:
            authoritative_keys.extend(
                need.key
                for need in needs_by_group.get(group, [])
                if need.key in question_needs_by_key
            )
        authoritative_keys = list(dict.fromkeys(authoritative_keys))
        missing_keys = [
            key
            for key in authoritative_keys
            if key in question_needs_by_key
            and key not in covered_missing_keys
            and key
            not in conditional_controller_keys_by_requirement.get(
                question_requirement_id, set()
            )
            and not question_needs_by_key[key].already_known
            and question_needs_by_key[key].evidence_group
            not in satisfied_reusable_groups
        ]
        if not missing_keys:
            return
        missing_needs = [question_needs_by_key[key] for key in missing_keys]
        question_text = (
            safe_owned_question_prompt(missing_needs)
            if reconstructed
            else question.question
        )
        if (
            any(key.casefold() in ai_reference_keys for key in missing_keys)
            and "AI 参考" not in question_text
            and "AI参考" not in question_text
        ):
            question_text = f"根据目前的 AI 参考信息，该项目可能有相关要求。{question_text}"
        if reconstructed or set(missing_keys) != set(authoritative_keys):
            filtered_fields = [
                field
                for field in question.fields
                if canonical_evidence_key(field.evidence_key)
                in missing_keys
            ]
            filtered_options = [
                option
                for option in question.options
                if option.evidence_key
                and canonical_evidence_key(option.evidence_key)
                in missing_keys
            ]
        else:
            filtered_fields = question.fields
            filtered_options = question.options
        questions.append(
            normalize_question_schema_safely(
                question.model_copy(
                    update={
                        "question_id": (
                            f"{question.question_id}:{question_requirement_id}"
                            if reconstructed
                            else question.question_id
                        ),
                        "question": question_text,
                        "prompt": question_text,
                        "requirement_id": question_requirement_id,
                        "fields": filtered_fields,
                        "options": filtered_options,
                    }
                ),
                missing_keys,
                question_needs_by_key,
                runtime_reusable_by_key,
            )
        )
        covered_missing_keys.update(missing_keys)

    for question in draft.questions:
        if not (question.prompt or question.question).strip():
            logger.warning("invalid_gap_question_prompt dropped")
            continue
        canonical_question_keys = list(
            dict.fromkeys(canonical_evidence_key(key) for key in question.evidence_keys)
        )
        schema_referenced_keys = list(canonical_question_keys)
        schema_referenced_keys.extend(
            canonical_evidence_key(field.evidence_key)
            for field in question.fields
        )
        schema_referenced_keys.extend(
            canonical_evidence_key(option.evidence_key)
            for option in question.options
            if option.evidence_key
        )
        schema_referenced_keys = list(dict.fromkeys(schema_referenced_keys))
        referenced_requirement_ids = {
            requirement_id
            for key in schema_referenced_keys
            for requirement_id in requirement_ids_by_key.get(key, [])
        }
        declared_requirement_id = question.requirement_id
        declared_is_valid = (
            declared_requirement_id in needs_by_requirement
            if declared_requirement_id
            else False
        )
        owner_candidates: Optional[Set[str]] = None
        for key in schema_referenced_keys:
            key_owners = set(requirement_ids_by_key.get(key, []))
            if not key_owners:
                continue
            owner_candidates = (
                key_owners
                if owner_candidates is None
                else owner_candidates.intersection(key_owners)
            )
        declared_owns_all = bool(
            declared_is_valid
            and all(
                key not in requirement_ids_by_key
                or declared_requirement_id in requirement_ids_by_key[key]
                for key in schema_referenced_keys
            )
        )
        if declared_owns_all:
            append_owned_question(
                question,
                declared_requirement_id,
                canonical_question_keys,
                reconstructed=False,
            )
            continue
        if not declared_requirement_id and owner_candidates:
            question_requirement_id = min(
                owner_candidates,
                key=lambda requirement_id: requirement_order[requirement_id],
            )
            append_owned_question(
                question,
                question_requirement_id,
                canonical_question_keys,
                reconstructed=False,
            )
            continue
        if referenced_requirement_ids:
            logger.warning(
                "cross_requirement_gap_question question_id=%s requirement_count=%d reconstructed=true",
                question.question_id,
                len(referenced_requirement_ids),
            )
            for requirement_id in sorted(
                referenced_requirement_ids,
                key=lambda item: requirement_order[item],
            ):
                owned_keys = [
                    key
                    for key in schema_referenced_keys
                    if requirement_id in requirement_ids_by_key.get(key, [])
                ]
                append_owned_question(
                    question,
                    requirement_id,
                    owned_keys,
                    reconstructed=True,
                )
            continue
        logger.warning(
            "unowned_gap_question question_id=%s dropped=true",
            question.question_id,
        )
        ownership_diagnostics = GapQuestionGenerationDiagnostics(
            requirement_id=question.requirement_id,
            allowed_evidence_keys=schema_referenced_keys,
            group_relation=question.group_relation,
            initial_schema=question_schema_snapshot(question),
            initial_failure_stage="ownership_failed",
            initial_validator_error="requirement_ownership_failed",
            final_failure_stage="ownership_failed",
        )
        log_question_generation_diagnostics(
            "ownership_failed",
            ownership_diagnostics,
        )

    for item in question_policy_requirements:
        if not item.evidence_needs:
            continue
        missing_needs = [
            need
            for need in item.evidence_needs
            if not need.already_known
            and need.key.casefold() not in covered_missing_keys
            and need.key
            not in conditional_controller_keys_by_requirement.get(
                item.requirement_id, set()
            )
            and need.evidence_group not in satisfied_reusable_groups
        ]
        if not missing_needs:
            continue
        question_prefix = (
            "根据目前的 AI 参考信息，该项目可能有这项要求。"
            if item.requirement_verification_status == "model_memory_unverified"
            else ""
        )
        questions.append(
            missing_structured_question(
                item,
                missing_needs,
                prompt=f"{question_prefix}{safe_owned_question_prompt(missing_needs)}",
            )
        )
        covered_missing_keys.update(need.key for need in missing_needs)

    questions, repair_calls = await repair_gap_questions_once(
        questions,
        {item.requirement_id: item for item in question_policy_requirements},
        runtime_reusable_by_key,
    )
    scope_legacy_material_evidence(planned, reusable_by_key)
    return GapPlan(
        target_program=request.target_program,
        requirements=[*planned, *excluded_requirements],
        questions=questions,
        reusable_evidence=list(reusable_by_key.values()),
        planning_llm_requests=1 + repair_calls,
    )


@app.post("/gap/plan", response_model=GapPlan, tags=["gap"])
async def gap_plan_endpoint(request: GapPlanRequest) -> GapPlan:
    """Plan one adaptive evidence interview without Web Search."""
    return await build_gap_plan(request)


@app.post(
    "/gap/questions/repair",
    response_model=GapPlannerQuestion,
    tags=["gap"],
)
async def gap_question_repair_endpoint(
    request: GapQuestionRepairRequest,
) -> GapPlannerQuestion:
    """Run one user-requested narrow repair for a single invalid question schema."""
    reusable = merge_reusable_evidence(
        request.user_profile,
        request.user_evidence,
    )
    diagnostics = request.question.generation_diagnostics
    if diagnostics:
        diagnostics = diagnostics.model_copy(
            update={
                "repair_schema": None,
                "repair_failure_stage": None,
                "repair_validator_error": None,
                "final_failure_stage": None,
            }
        )
    repaired, _ = await repair_gap_questions_once(
        [
            request.question.model_copy(
                update={
                    "schema_status": "invalid",
                    "repair_attempts": 0,
                    "generation_diagnostics": diagnostics,
                }
            )
        ],
        {request.requirement.requirement_id: request.requirement},
        {canonical_evidence_key(item.key): item for item in reusable},
    )
    return repaired[0]


UNKNOWN_ANSWER_MARKERS = (
    "不知道", "不记得", "不清楚", "不了解", "忘了", "忘记", "不确定", "无法提供", "记不清",
)
NEGATIVE_ANSWER_MARKERS = (
    "没有", "没考", "未考", "没修过", "未修过", "没学过", "未学过", "没上过", "未上过",
    "未准备", "还没准备", "暂无", "暂时没有", "没有准备", "没相关", "无",
)

EVIDENCE_ALIASES_BY_KEY = {
    "ielts": ("ielts", "雅思"),
    "toefl": ("toefl", "托福"),
    "gre": ("gre",),
    "gmat": ("gmat",),
    "gpa": ("gpa", "绩点"),
    "average_score": ("average", "平均分", "均分"),
    "degree_classification": ("degree classification", "degree class", "学位等级", "学位"),
    "experience": ("experience", "经历", "经验", "实习", "工作", "科研", "项目"),
    "portfolio": ("portfolio", "作品集"),
    "recommendations": ("recommend", "reference", "推荐信", "推荐人"),
    "statement_of_purpose": ("statement of purpose", "personal statement", "sop", "个人陈述", "动机信"),
    "personal_statement": ("statement of purpose", "personal statement", "ps", "个人陈述", "动机信"),
    "cv": ("cv", "résumé", "resume", "简历"),
    "transcript": ("transcript", "成绩单"),
    "degree_certificate": ("degree certificate", "diploma", "学位证", "学历证明", "毕业证"),
}


def evidence_aliases(key: str) -> tuple[str, ...]:
    matches = [
        (len(marker), aliases)
        for marker, aliases in EVIDENCE_ALIASES_BY_KEY.items()
        if marker in key.casefold()
    ]
    return max(matches, default=(0, ()))[1]


def answer_mentions_evidence_key(answer: str, key: str) -> bool:
    lowered = answer.casefold()
    return any(alias.casefold() in lowered for alias in evidence_aliases(key))


def parse_expected_education_values(
    answer: str,
    expected_keys: List[str],
) -> Dict[str, str]:
    expected = {key.casefold() for key in expected_keys}
    university_key = "education.university"
    major_key = "education.major"
    if not expected.intersection({university_key, major_key}):
        return {}
    cleaned = answer.strip().strip("，,；;。")
    values: Dict[str, str] = {}
    university_match = re.match(
        r"^(.+?(?:大学|学院|university|college))\s*[，,；;]?\s*(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if university_match:
        if university_key in expected:
            values[university_key] = university_match.group(1).strip()
        remainder = university_match.group(2).strip()
        if major_key in expected and remainder:
            values[major_key] = remainder
        return values

    if len(expected) == 1 and cleaned:
        if university_key in expected:
            values[university_key] = cleaned
        elif major_key in expected:
            values[major_key] = cleaned
        return values

    parts = [part for part in re.split(r"\s+|[，,；;]", cleaned) if part]
    if university_key in expected and major_key in expected and len(parts) >= 2:
        values[university_key] = parts[0]
        values[major_key] = " ".join(parts[1:])
    elif university_key in expected and (
        "大学" in cleaned or "学院" in cleaned or "university" in cleaned.casefold()
    ):
        values[university_key] = cleaned
    elif major_key in expected and (
        "专业" in cleaned or "major" in cleaned.casefold()
    ):
        values[major_key] = cleaned
    return values


COURSE_SLOT_GENERIC_TERMS = {
    "course",
    "courses",
    "class",
    "classes",
    "module",
    "modules",
    "subject",
    "subjects",
    "math",
    "mathematics",
}
COURSE_AGGREGATE_MARKERS = (
    "credit",
    "credits",
    "ects",
    "credit hour",
    "credit hours",
    "学分",
    "总学时",
)


def course_slot_terms(need: GapEvidenceNeed) -> List[str]:
    key_leaf = need.key.casefold().rsplit(".", 1)[-1]
    key_parts = [
        part
        for part in re.split(r"[_\-\s]+", key_leaf)
        if len(part) >= 3 and part not in COURSE_SLOT_GENERIC_TERMS
    ]
    label_parts = [
        part.casefold()
        for part in re.findall(r"[A-Za-z][A-Za-z0-9-]*|[\u4e00-\u9fff]+", need.label)
        if len(part) >= 2 and part.casefold() not in COURSE_SLOT_GENERIC_TERMS
    ]
    phrases = [" ".join(key_parts), need.label.strip().casefold()]
    return list(
        dict.fromkeys(
            term
            for term in [*phrases, *key_parts, *label_parts]
            if term and term not in COURSE_SLOT_GENERIC_TERMS
        )
    )


def text_term_span(text: str, term: str) -> Optional[tuple[int, int]]:
    pattern = (
        rf"\b{re.escape(term)}\b"
        if re.fullmatch(r"[a-z0-9 -]+", term, re.IGNORECASE)
        else re.escape(term)
    )
    match = re.search(pattern, text, re.IGNORECASE)
    return match.span() if match else None


def answer_clause_around_span(answer: str, span: tuple[int, int]) -> str:
    start, end = span
    left = max(
        [answer.rfind(separator, 0, start) for separator in ("，", ",", "、", "；", ";", "。", "\n")]
        + [-1]
    ) + 1
    right_positions = [
        answer.find(separator, end)
        for separator in ("，", ",", "、", "；", ";", "。", "\n")
        if answer.find(separator, end) >= 0
    ]
    right = min(right_positions) if right_positions else len(answer)
    return answer[left:right].strip()


def course_slot_is_aggregate(need: GapEvidenceNeed) -> bool:
    descriptor = f"{need.key} {need.label}".casefold().replace("_", " ")
    return any(marker in descriptor for marker in COURSE_AGGREGATE_MARKERS)


def parse_expected_course_slot(
    need: GapEvidenceNeed,
    answer: str,
) -> Optional[tuple[EvidenceAvailability, Any]]:
    if need.evidence_type != "courses" and not need.key.casefold().startswith("courses."):
        return None

    stripped = answer.strip()
    lowered = stripped.casefold()
    key_leaf = need.key.casefold().rsplit(".", 1)[-1]
    aggregate = course_slot_is_aggregate(need)
    if aggregate:
        quantity_match = re.search(
            r"\d+(?:\.\d+)?\s*(?:ects|credits?|credit\s*hours?|学分|学时)",
            lowered,
            re.IGNORECASE,
        )
        aggregate_span = next(
            (
                span
                for marker in COURSE_AGGREGATE_MARKERS
                if (span := text_term_span(lowered, marker)) is not None
            ),
            None,
        )
        if quantity_match:
            return "known", {"description": quantity_match.group(0)}
        if aggregate_span:
            clause = answer_clause_around_span(stripped, aggregate_span).casefold()
            if any(marker in clause for marker in UNKNOWN_ANSWER_MARKERS):
                return "unknown", None
            if any(marker in clause for marker in NEGATIVE_ANSWER_MARKERS):
                return "known_negative", None
        return None

    if key_leaf in {"course", "courses"}:
        if any(marker in lowered for marker in UNKNOWN_ANSWER_MARKERS):
            return "unknown", None
        if any(marker in lowered for marker in NEGATIVE_ANSWER_MARKERS):
            return "known_negative", None
        return "known", {"description": stripped}

    matched_span = next(
        (
            span
            for term in course_slot_terms(need)
            if (span := text_term_span(lowered, term)) is not None
        ),
        None,
    )
    if matched_span is None:
        return None
    clause = answer_clause_around_span(stripped, matched_span).casefold()
    if any(marker in clause for marker in UNKNOWN_ANSWER_MARKERS):
        return "unknown", None
    if any(marker in clause for marker in NEGATIVE_ANSWER_MARKERS):
        return "known_negative", None
    return "known", {"description": answer[matched_span[0] : matched_span[1]]}


def compound_material_availability(answer: str, key: str) -> Optional[EvidenceAvailability]:
    if "materials." not in key.casefold():
        return None
    lowered = answer.casefold()
    excluded_match = re.search(
        r"除了(.+?)(?:以外|之外)?(?:都|其余).*(?:有|齐|准备)",
        lowered,
    ) or re.search(r"everything\s+except\s+(.+)", lowered)
    if excluded_match:
        excluded = excluded_match.group(1)
        return (
            "known_negative"
            if any(alias.casefold() in excluded for alias in evidence_aliases(key))
            else "known"
        )
    if re.search(r"^(?:这些|材料)?(?:我)?(?:都|全部)(?:有|齐了|准备好了)", lowered):
        return "known"
    if re.search(r"^(?:这些|材料)?(?:我)?(?:都|全部)(?:没有|没准备)", lowered):
        return "known_negative"
    return None


def evidence_answer_clause(answer: str, key: str) -> str:
    lowered = answer.casefold()
    aliases = evidence_aliases(key)
    positions = [lowered.find(alias.casefold()) for alias in aliases]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return answer
    position = min(positions)
    start = max(
        [lowered.rfind(separator, 0, position) for separator in "，,；;。\n"]
        + [-1]
    ) + 1
    ends = [
        lowered.find(separator, position)
        for separator in "，,；;。\n"
        if lowered.find(separator, position) >= 0
    ]
    end = min(ends) if ends else len(answer)
    return answer[start:end]


NUMERIC_EVIDENCE_FIELDS = {"score", "scale", "quantity", "duration"}


def contextual_numeric_values(
    answer: str,
    question_keys: List[str],
    need_by_key: Dict[str, GapEvidenceNeed],
    existing_by_key: Dict[str, UserEvidence],
) -> Dict[str, tuple[Any, str]]:
    numeric_slots = []
    for key in question_keys:
        need = need_by_key.get(key.casefold())
        if need is None:
            continue
        required_fields = need.required_fields or required_fields_for_evidence_need(
            need,
            GapDeterministicConstraint(),
        )
        existing = existing_by_key.get(key.casefold())
        if existing and existing.availability == "known":
            required_fields = missing_evidence_fields(need, existing.value)
        elif existing and existing.availability in {"known_negative", "unknown"}:
            required_fields = []
        numeric_slots.extend(
            (need.key, field)
            for field in required_fields
            if field in NUMERIC_EVIDENCE_FIELDS
        )
    if len(numeric_slots) != 1:
        return {}

    numeric_clauses = []
    for clause in re.split(r"[，,；;。\n]", answer):
        stripped = clause.strip()
        if not stripped or any(
            marker in stripped.casefold()
            for marker in (*UNKNOWN_ANSWER_MARKERS, *NEGATIVE_ANSWER_MARKERS)
        ):
            continue
        numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", stripped)
        if len(numbers) == 1:
            numeric_clauses.append((float(numbers[0]), stripped))
    if len(numeric_clauses) != 1:
        return {}

    key, field = numeric_slots[0]
    number, clause = numeric_clauses[0]
    return {key.casefold(): ({field: number}, clause)}


def classification_like_answer(answer: str) -> bool:
    normalized = re.sub(r"\s+", " ", answer.strip().casefold()).strip("，,；;。.!！")
    chinese = re.fullmatch(
        r"(?:本科)?(?:一等|二等一|二等二|二等一级|二等二级|三等)(?:荣誉)?(?:学位)?",
        normalized,
    )
    english = re.fullmatch(
        r"(?:first(?:[- ]class)?|upper[- ]second(?:[- ]class)?|"
        r"lower[- ]second(?:[- ]class)?|second[- ]class[- ]upper|"
        r"second[- ]class[- ]lower|2\s*:\s*1|2\s*:\s*2)(?:\s+(?:degree|honours?))?",
        normalized,
    )
    return bool(chinese or english)


def contextual_any_group_values(
    answer: str,
    question_keys: List[str],
    need_by_key: Dict[str, GapEvidenceNeed],
    existing_by_key: Dict[str, UserEvidence],
) -> tuple[Dict[str, tuple[Any, str]], List[str], set[str]]:
    """Choose an academic ANY branch from value form without requiring field aliases."""
    question_key_set = {key.casefold() for key in question_keys}
    groups: Dict[str, List[GapEvidenceNeed]] = {}
    for need in need_by_key.values():
        if (
            need.key.casefold() in question_key_set
            and need.evidence_group
            and need.group_relation == "any"
        ):
            groups.setdefault(need.evidence_group, []).append(need)

    values: Dict[str, tuple[Any, str]] = {}
    clarification_slots: List[str] = []
    clarification_keys: set[str] = set()
    stripped = answer.strip()
    lowered = stripped.casefold()
    numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", stripped)
    for needs in groups.values():
        if any(
            evidence_satisfies_need(need, existing_by_key[need.key.casefold()])
            for need in needs
            if need.key.casefold() in existing_by_key
        ):
            continue
        classification_need = next(
            (
                need
                for need in needs
                if need.key.casefold().rsplit(".", 1)[-1] == "degree_classification"
            ),
            None,
        )
        gpa_need = next(
            (need for need in needs if need.key.casefold().rsplit(".", 1)[-1] == "gpa"),
            None,
        )
        average_need = next(
            (
                need
                for need in needs
                if need.key.casefold().rsplit(".", 1)[-1] == "average_score"
            ),
            None,
        )
        if classification_need and classification_like_answer(stripped):
            values[classification_need.key.casefold()] = (
                {"description": stripped},
                stripped,
            )
            continue
        if len(numbers) != 1 or not (gpa_need and average_need):
            continue
        number = float(numbers[0])
        has_gpa_semantics = bool(re.search(r"\bgpa\b|绩点", lowered, re.IGNORECASE))
        has_average_semantics = bool(
            re.search(r"平均分|均分|average(?:\s+score)?|百分制", lowered, re.IGNORECASE)
            or re.fullmatch(r"\s*\d+(?:\.\d+)?\s*分\s*", stripped)
        )
        if has_gpa_semantics and not has_average_semantics:
            values[gpa_need.key.casefold()] = ({"score": number}, stripped)
        elif has_average_semantics and not has_gpa_semantics:
            values[average_need.key.casefold()] = ({"score": number}, stripped)
        elif re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", stripped):
            clarification_keys.update(need.key.casefold() for need in needs)
            for need in (gpa_need, average_need):
                required_fields = need.required_fields or ["score"]
                clarification_slots.extend(
                    f"{need.key}.{field}"
                    for field in required_fields
                    if field in NUMERIC_EVIDENCE_FIELDS
                )
    return values, list(dict.fromkeys(clarification_slots)), clarification_keys


def parse_evidence_value(key: str, answer: str) -> Any:
    lowered_key = key.casefold()
    key_leaf = lowered_key.rsplit(".", 1)[-1]
    if lowered_key == "gpa" and not re.search(r"\bgpa\b", answer, re.IGNORECASE):
        if re.search(r"平均分|均分|average", answer, re.IGNORECASE):
            return None
    score_keys = ("gpa", "average_score", "ielts", "toefl", "gre", "gmat")
    if key_leaf in score_keys:
        numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", answer)]
        if not numbers:
            return None
        scale_match = re.search(r"\d+(?:\.\d+)?\s*/\s*(\d+(?:\.\d+)?)", answer)
        subscores = {}
        component_aliases = {
            "listening": ("listening", "听力", "l"),
            "reading": ("reading", "阅读", "r"),
            "writing": ("writing", "写作", "w"),
            "speaking": ("speaking", "口语", "s"),
        }
        for component, aliases in component_aliases.items():
            for alias in aliases:
                alias_pattern = (
                    rf"\b{re.escape(alias)}\b"
                    if len(alias) == 1 and alias.isascii()
                    else rf"(?:\b{re.escape(alias)}\b|{re.escape(alias)})"
                )
                match = re.search(
                    rf"{alias_pattern}\s*[:：]?\s*(\d+(?:\.\d+)?)",
                    answer,
                    re.IGNORECASE,
                )
                if match:
                    subscores[component] = float(match.group(1))
                    break
        overall_match = re.search(
            r"(?:overall|总分)\s*[:：]?\s*(\d+(?:\.\d+)?)",
            answer,
            re.IGNORECASE,
        )
        score = (
            float(overall_match.group(1))
            if overall_match
            else None if subscores else numbers[0]
        )
        return {
            "score": score,
            "scale": float(scale_match.group(1)) if scale_match else None,
            "subscores": subscores,
        }
    if "recommend" in lowered_key or "quantity" in lowered_key:
        match = re.search(r"\d+(?:\.\d+)?", answer)
        return {"quantity": float(match.group())} if match else None
    if "course" in lowered_key:
        return {"description": answer}
    if "experience" in lowered_key:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(年|years?|个月|months?)", answer, re.IGNORECASE)
        value: Dict[str, Any] = {"description": answer}
        if match:
            value["duration"] = float(match.group(1))
            value["unit"] = match.group(2)
        return value
    return {"description": answer}


def merge_evidence_value(existing: Any, incoming: Any) -> Any:
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        return incoming
    merged = {**existing}
    for key, value in incoming.items():
        if key == "subscores" and isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        elif value is not None:
            merged[key] = value
    return merged


def missing_evidence_fields(need: GapEvidenceNeed, value: Any) -> List[str]:
    required_fields = need.required_fields or required_fields_for_evidence_need(
        need,
        GapDeterministicConstraint(),
    )
    if need.other_value_kind is not None:
        if (
            need.other_value_kind == "boolean"
            and isinstance(value, dict)
            and isinstance(value.get("matches_condition"), bool)
        ):
            return []
        typed_value = value.get("value") if isinstance(value, dict) else None
        if need.other_value_kind == "boolean":
            complete = isinstance(typed_value, bool)
        elif need.other_value_kind == "numeric":
            complete = isinstance(typed_value, (int, float)) and not isinstance(
                typed_value, bool
            )
        elif need.other_value_kind in {"single_select", "short_text"}:
            complete = isinstance(typed_value, str) and bool(typed_value.strip())
        else:
            complete = isinstance(typed_value, list) and bool(typed_value)
        return [] if complete else required_fields
    if not isinstance(value, dict):
        if required_fields == ["description"] and value not in (None, "", []):
            return []
        return required_fields
    if need.evidence_type == "experience":
        has_experience = value.get("has_experience")
        if has_experience is False:
            return []
        missing = []
        if has_experience is not True:
            missing.append("has_experience")
        experience_types = value.get("experience_types")
        if not isinstance(experience_types, list) or not experience_types:
            missing.append("experience_types")
        duration = value.get("duration")
        if not isinstance(duration, dict) or not isinstance(
            duration.get("quantity"), (int, float)
        ):
            missing.append("duration")
        if not isinstance(duration, dict) or duration.get("unit") not in {
            "months", "years"
        }:
            missing.append("unit")
        return [field for field in required_fields if field in missing]
    missing = []
    for field in required_fields:
        if field in {"listening", "reading", "writing", "speaking"}:
            present = value.get("subscores", {}).get(field) is not None
        elif field == "status":
            present = True
        else:
            present = value.get(field) is not None
        if not present:
            missing.append(field)
    return missing


def evidence_slot_label(slot: str) -> str:
    key, field = slot.rsplit(".", 1)
    evidence_labels = {
        "education.university": "本科院校",
        "education.major": "本科专业",
    }
    if key in evidence_labels:
        return evidence_labels[key]
    field_labels = {
        "score": "总分",
        "listening": "听力",
        "reading": "阅读",
        "writing": "写作",
        "speaking": "口语",
        "quantity": "数量",
        "duration": "时长",
        "description": "具体信息",
        "status": "准备状态",
    }
    friendly_name = friendly_evidence_name(key)
    if friendly_name != "相关信息":
        if field == "description":
            return friendly_name
        if field == "score":
            return f"{friendly_name}分数"
        return f"{friendly_name}{field_labels.get(field, field)}"
    return f"{key} 的{field_labels.get(field, field)}"


def evidence_satisfies_need(need: GapEvidenceNeed, item: UserEvidence) -> bool:
    if item.availability != "known":
        return False
    if missing_evidence_fields(need, item.value):
        return False
    if need.minimum is not None:
        if not isinstance(item.value, dict) or item.value.get("score") is None:
            return False
        if float(item.value["score"]) < need.minimum:
            return False
    if need.component_minimum is not None:
        subscores = item.value.get("subscores", {}) if isinstance(item.value, dict) else {}
        if any(
            subscores.get(component) is None
            or float(subscores[component]) < need.component_minimum
            for component in ("listening", "reading", "writing", "speaking")
        ):
            return False
    if need.required_quantity is not None:
        if not isinstance(item.value, dict) or item.value.get("quantity") is None:
            return False
        if float(item.value["quantity"]) < need.required_quantity:
            return False
    return True


def evidence_is_terminal_for_need(
    need: GapEvidenceNeed,
    item: UserEvidence,
) -> bool:
    if item.availability in {"known_negative", "unknown"}:
        return True
    return item.availability == "known" and not missing_evidence_fields(need, item.value)


IELTS_COMPONENT_FIELDS = ("listening", "reading", "writing", "speaking")


def collective_ielts_component_value(
    answer: str,
    need: GapEvidenceNeed,
    existing: Optional[UserEvidence],
) -> Optional[Dict[str, Any]]:
    if canonical_evidence_key(need.key) != "ielts":
        return None
    required_fields = need.required_fields or ["score"]
    existing_value = (
        existing.value
        if existing and existing.availability == "known" and isinstance(existing.value, dict)
        else {}
    )
    missing_fields = missing_evidence_fields(need, existing_value)
    if not missing_fields or any(
        field not in IELTS_COMPONENT_FIELDS for field in missing_fields
    ):
        return None
    match = re.fullmatch(
        r"\s*(?:(?:四项|各项)\s*)?(?:都是|全部(?:都是)?|全是)\s*[:：]?\s*"
        r"(\d+(?:\.\d+)?)\s*[。.!！]?\s*",
        answer,
        re.IGNORECASE,
    )
    if not match:
        return None
    score = float(match.group(1))
    return {
        "subscores": {field: score for field in missing_fields},
    }


def parse_gap_evidence(request: GapEvidenceParseRequest) -> GapEvidenceParseResponse:
    now = datetime.now(timezone.utc).isoformat()
    evidence = []
    missing_slots = []
    canonical_needs = [
        need.model_copy(update={"key": canonical_evidence_key(need.key)})
        for need in request.evidence_needs
    ]
    need_by_key = {need.key: need for need in canonical_needs}
    existing_by_key = {
        canonical_evidence_key(item.key): item.model_copy(
            update={"key": canonical_evidence_key(item.key)}
        )
        for item in request.existing_evidence
    }
    question_keys = list(
        dict.fromkeys(
            canonical_evidence_key(key) for key in request.question.evidence_keys
        )
    )
    multiple_keys = len(question_keys) > 1
    stripped_answer = request.answer.strip().casefold()
    globally_unknown = bool(
        re.fullmatch(r"(?:我)?(?:都|全部)?(?:不知道|不记得|不清楚|不了解|不确定|记不清|无法提供)[。.!！]?", stripped_answer)
    )
    globally_negative = bool(
        re.fullmatch(r"(?:我)?(?:都|全部)?(?:无|没有|暂时没有|暂无|没考|未考)[。.!！]?", stripped_answer)
    )
    education_values = parse_expected_education_values(
        request.answer,
        question_keys,
    )
    any_group_values, clarification_slots, clarification_group_keys = (
        contextual_any_group_values(
            request.answer,
            question_keys,
            need_by_key,
            existing_by_key,
        )
    )
    numeric_values = contextual_numeric_values(
        request.answer,
        question_keys,
        need_by_key,
        existing_by_key,
    )
    numeric_values.update(any_group_values)
    for key in question_keys:
        need = need_by_key.get(key)
        if need is None:
            continue
        collective_ielts = collective_ielts_component_value(
            request.answer,
            need,
            existing_by_key.get(key),
        )
        if collective_ielts is not None:
            numeric_values[key] = (collective_ielts, request.answer)
        required_fields = need.required_fields or required_fields_for_evidence_need(
            need,
            GapDeterministicConstraint(),
        )
        education_value = education_values.get(need.key)
        if need.key in {"education.university", "education.major"}:
            if globally_unknown:
                availability: EvidenceAvailability = "unknown"
                value = None
            elif globally_negative:
                availability = "known_negative"
                value = None
            elif education_value:
                availability = "known"
                value = education_value
            else:
                missing_slots.extend(f"{need.key}.{field}" for field in required_fields)
                continue
            evidence.append(
                UserEvidence(
                    evidence_type=need.evidence_type,
                    key=need.key,
                    value=value,
                    raw_answer=request.answer,
                    availability=availability,
                    updated_at=now,
                )
            )
            continue
        if need.evidence_type == "courses" or need.key.casefold().startswith("courses."):
            if globally_unknown:
                course_result: Optional[tuple[EvidenceAvailability, Any]] = (
                    "unknown",
                    None,
                )
            elif globally_negative:
                course_result = ("known_negative", None)
            else:
                course_result = parse_expected_course_slot(need, request.answer)
            if course_result is None:
                missing_slots.extend(f"{need.key}.{field}" for field in required_fields)
                continue
            availability, value = course_result
            evidence.append(
                UserEvidence(
                    evidence_type=need.evidence_type,
                    key=need.key,
                    value=value,
                    raw_answer=request.answer,
                    availability=availability,
                    updated_at=now,
                )
            )
            continue
        compound_availability = compound_material_availability(request.answer, key)
        contextual_numeric = numeric_values.get(need.key)
        if (
            multiple_keys
            and compound_availability is None
            and contextual_numeric is None
            and not globally_unknown
            and not globally_negative
            and not answer_mentions_evidence_key(request.answer, key)
        ):
            missing_slots.extend(f"{need.key}.{field}" for field in required_fields)
            continue
        clause = (
            contextual_numeric[1]
            if contextual_numeric is not None
            else request.answer
            if not multiple_keys
            else evidence_answer_clause(request.answer, key)
        ).strip()
        if compound_availability is not None:
            availability = compound_availability
        elif globally_unknown or any(marker in clause.casefold() for marker in UNKNOWN_ANSWER_MARKERS):
            availability: EvidenceAvailability = "unknown"
        elif globally_negative or any(marker in clause.casefold() for marker in NEGATIVE_ANSWER_MARKERS):
            availability = "known_negative"
        else:
            availability = "known"
        value = (
            contextual_numeric[0]
            if availability == "known" and contextual_numeric is not None
            else parse_evidence_value(key, clause)
            if availability == "known"
            else None
        )
        if availability == "known" and value is None:
            missing_slots.extend(f"{need.key}.{field}" for field in required_fields)
            continue
        existing = existing_by_key.get(need.key)
        if availability == "known" and existing and existing.availability == "known":
            value = merge_evidence_value(existing.value, value)
        if availability == "known":
            missing_fields = missing_evidence_fields(need, value)
            missing_slots.extend(f"{need.key}.{field}" for field in missing_fields)
        evidence.append(
            UserEvidence(
                evidence_type=need.evidence_type,
                key=need.key,
                value=value,
                raw_answer=request.answer,
                availability=availability,
                updated_at=now,
            )
        )
    combined_evidence = {**existing_by_key}
    combined_evidence.update({canonical_evidence_key(item.key): item for item in evidence})
    any_groups: Dict[str, List[GapEvidenceNeed]] = {}
    for need in canonical_needs:
        if need.evidence_group and need.group_relation == "any":
            any_groups.setdefault(need.evidence_group, []).append(need)
    satisfied_groups = [
        group
        for group, needs in any_groups.items()
        if any(
            evidence_satisfies_need(need, combined_evidence[need.key.casefold()])
            for need in needs
            if need.key in combined_evidence
        )
    ]
    if satisfied_groups:
        group_by_key = {
            need.key: need.evidence_group
            for need in canonical_needs
        }
        missing_slots = [
            slot
            for slot in missing_slots
            if group_by_key.get(
                next(
                    (
                        need.key
                        for need in canonical_needs
                        if slot.startswith(f"{need.key}.")
                    ),
                    "",
                )
            )
            not in satisfied_groups
        ]
    unique_missing_slots = list(dict.fromkeys(missing_slots))
    if clarification_slots and not satisfied_groups:
        unique_missing_slots = [
            slot
            for slot in unique_missing_slots
            if not any(
                slot.startswith(f"{need.key}.")
                and need.key in clarification_group_keys
                for need in canonical_needs
            )
        ]
        unique_missing_slots.extend(
            slot for slot in clarification_slots if slot not in unique_missing_slots
        )
    evidence_by_key = {canonical_evidence_key(item.key): item for item in evidence}
    slot_states: Dict[str, EvidenceSlotStatus] = {
        slot: "missing" for slot in unique_missing_slots
    }
    for need in canonical_needs:
        item = evidence_by_key.get(need.key)
        if item is None:
            continue
        required_fields = need.required_fields or required_fields_for_evidence_need(
            need,
            GapDeterministicConstraint(),
        )
        for field in required_fields:
            slot = f"{need.key}.{field}"
            if slot not in slot_states:
                slot_states[slot] = item.availability
    if clarification_slots and not satisfied_groups:
        follow_up = "请确认这个数字属于 GPA（绩点）还是百分制平均分？"
    else:
        follow_up = (
            f"还需要补充：{'、'.join(evidence_slot_label(slot) for slot in unique_missing_slots)}。"
            "如果确实不知道或不记得，可以直接说明。"
            if unique_missing_slots
            else None
        )
    return GapEvidenceParseResponse(
        evidence=evidence,
        missing_slots=unique_missing_slots,
        follow_up_question=follow_up,
        satisfied_evidence_groups=satisfied_groups,
        slot_states=slot_states,
        parser_calls=1,
    )


@app.post("/gap/evidence/parse", response_model=GapEvidenceParseResponse, tags=["gap"])
async def gap_evidence_parse_endpoint(
    request: GapEvidenceParseRequest,
) -> GapEvidenceParseResponse:
    """Parse one answer locally; this endpoint never calls an LLM."""
    return parse_gap_evidence(request)


def assign_typed_evidence_path(value: Dict[str, Any], path: str, answer: Any) -> None:
    if path in IELTS_COMPONENT_FIELDS:
        value.setdefault("subscores", {})[path] = answer
    else:
        value[path] = answer


def structured_evidence_missing_slots(
    needs: List[GapEvidenceNeed],
    evidence_by_key: Dict[str, UserEvidence],
) -> tuple[List[str], List[str]]:
    missing_slots = []
    groups: Dict[str, List[GapEvidenceNeed]] = {}
    for need in needs:
        key = canonical_evidence_key(need.key)
        item = evidence_by_key.get(key)
        if item is None:
            missing_slots.extend(
                f"{key}.{field}" for field in (need.required_fields or ["description"])
            )
        elif item.availability == "known":
            missing_slots.extend(
                f"{key}.{field}"
                for field in missing_evidence_fields(need, item.value)
            )
        if need.evidence_group and need.group_relation == "any":
            groups.setdefault(need.evidence_group, []).append(need)

    satisfied_groups = []
    for group, group_needs in groups.items():
        academic_policy_group = all(
            need.evidence_type == "academic_score"
            and canonical_evidence_key(need.key).rsplit(".", 1)[-1]
            in ACADEMIC_POLICY_KEYS
            for need in group_needs
        )
        language_policy_group = all(
            backend_language_proof(need) is not None
            for need in group_needs
        )
        if academic_policy_group:
            satisfied = any(
                (item := evidence_by_key.get(canonical_evidence_key(need.key)))
                is not None
                and evidence_is_terminal_for_need(need, item)
                for need in group_needs
            )
        elif language_policy_group:
            satisfied = any(
                evidence_is_complete_known(
                    need,
                    evidence_by_key.get(canonical_evidence_key(need.key)),
                )
                for need in group_needs
            ) or all(
                (item := evidence_by_key.get(canonical_evidence_key(need.key)))
                is not None
                and evidence_is_terminal_for_need(need, item)
                for need in group_needs
            )
        else:
            satisfied = any(
                (item := evidence_by_key.get(canonical_evidence_key(need.key)))
                is not None
                and evidence_satisfies_need(need, item)
                for need in group_needs
            ) or all(
                (item := evidence_by_key.get(canonical_evidence_key(need.key)))
                is not None
                and evidence_is_terminal_for_need(need, item)
                for need in group_needs
            )
        if satisfied:
            satisfied_groups.append(group)
    if satisfied_groups:
        keys_in_satisfied_groups = {
            canonical_evidence_key(need.key)
            for group in satisfied_groups
            for need in groups[group]
        }
        missing_slots = [
            slot
            for slot in missing_slots
            if not any(slot.startswith(f"{key}.") for key in keys_in_satisfied_groups)
        ]
    return list(dict.fromkeys(missing_slots)), satisfied_groups


def structured_terminal_evidence_keys(
    question: GapPlannerQuestion,
    expected_keys: Set[str],
) -> Set[str]:
    """Limit a terminal action to the evidence branches rendered by the control."""
    bound_keys = {
        canonical_evidence_key(field.evidence_key)
        for field in question.fields
    }
    bound_keys.update(
        canonical_evidence_key(option.evidence_key)
        for option in question.options
        if option.evidence_key
    )
    return expected_keys.intersection(bound_keys) or expected_keys


def submit_structured_evidence(
    request: GapStructuredEvidenceRequest,
) -> GapEvidenceParseResponse:
    question = request.question
    if question.control_type == "text_fallback":
        raise HTTPException(
            status_code=422,
            detail="text_fallback answers must use the free-text parser endpoint",
        )
    needs = [
        need.model_copy(update={"key": canonical_evidence_key(need.key)})
        for need in request.evidence_needs
    ]
    need_by_key = {need.key: need for need in needs}
    expected_keys = {
        canonical_evidence_key(key) for key in question.expected_evidence_keys
    }
    allowed_keys = {
        canonical_evidence_key(key)
        for key in (question.allowed_evidence_keys or question.expected_evidence_keys)
    }
    controller_bindings_by_key = {
        canonical_evidence_key(binding.evidence_key): binding
        for binding in question.conditional_controller_bindings
    }
    if (
        not expected_keys
        or not expected_keys.issubset(allowed_keys)
        or not allowed_keys.issubset(need_by_key)
        or any(
            canonical_evidence_key(binding.evidence_key) not in allowed_keys
            for binding in question.conditional_controller_bindings
        )
    ):
        logger.warning(
            "structured_evidence_contract_invalid question_id=%s expected=%s allowed=%s needs=%s",
            question.question_id,
            sorted(expected_keys),
            sorted(allowed_keys),
            sorted(need_by_key),
        )
        raise HTTPException(status_code=422, detail="structured_question_unavailable")

    now = datetime.now(timezone.utc).isoformat()
    submitted: Dict[str, UserEvidence] = {}
    if request.answer.terminal_state:
        if (
            request.answer.terminal_state == "unknown"
            and not question.allow_unknown
        ):
            raise HTTPException(status_code=422, detail="unknown is not allowed for this question")
        if (
            request.answer.terminal_state == "known_negative"
            and not question.allow_negative
        ):
            raise HTTPException(status_code=422, detail="negative is not allowed for this question")
        for key in structured_terminal_evidence_keys(question, expected_keys):
            need = need_by_key[key]
            raw = "不知道" if request.answer.terminal_state == "unknown" else "暂时没有"
            submitted[key] = UserEvidence(
                evidence_type=need.evidence_type,
                key=key,
                value=None,
                raw_answer=raw,
                availability=request.answer.terminal_state,
                updated_at=now,
            )
    elif question.control_type == "experience_form":
        option_by_value = {option.value: option for option in question.options}
        selected_values = list(dict.fromkeys(request.answer.selected_options))
        if any(value not in option_by_value for value in selected_values):
            raise HTTPException(status_code=422, detail="selected option is invalid")
        selected_types = [
            value.split(":", 1)[1]
            for value in selected_values
            if value.startswith("experience:") and value != "experience:none"
        ]
        selected_none = "experience:none" in selected_values
        if selected_none and selected_types:
            raise HTTPException(
                status_code=422,
                detail="no experience cannot be combined with experience types",
            )
        selected_units = [
            value.split(":", 1)[1]
            for value in selected_values
            if value.startswith("unit:")
        ]
        if len(selected_units) > 1:
            raise HTTPException(status_code=422, detail="experience unit must be unique")
        existing = next(
            (
                item
                for item in request.existing_evidence
                if canonical_evidence_key(item.key) == "experience"
                and item.availability == "known"
                and isinstance(item.value, dict)
            ),
            None,
        )
        existing_value = dict(existing.value) if existing else {}
        if selected_none:
            value = ExperienceEvidenceValue(
                requirement_id=question.requirement_id or "",
                has_experience=False,
            ).model_dump()
            raw_answer = "没有相关经历"
        else:
            experience_types = selected_types or existing_value.get(
                "experience_types", []
            )
            quantity = request.answer.values.get("experience-duration")
            existing_duration = existing_value.get("duration")
            existing_duration = (
                existing_duration if isinstance(existing_duration, dict) else {}
            )
            if quantity is None:
                quantity = existing_duration.get("quantity")
            unit = selected_units[0] if selected_units else existing_duration.get("unit")
            value = ExperienceEvidenceValue(
                requirement_id=question.requirement_id or "",
                has_experience=True,
                experience_types=experience_types,
                duration={"quantity": quantity, "unit": unit},
            ).model_dump()
            raw_answer = "；".join(
                [
                    *[
                        option_by_value[selected].label
                        for selected in selected_values
                        if selected.startswith("experience:")
                    ],
                    f"累计 {quantity} {unit}",
                ]
            )
        submitted["experience"] = UserEvidence(
            evidence_type="experience",
            key="experience",
            value=value,
            raw_answer=raw_answer,
            availability="known",
            updated_at=now,
            source_requirement_ids=(
                [question.requirement_id] if question.requirement_id else []
            ),
        )
    elif question.control_type in {
        "boolean", "boolean_group", "number", "number_group", "date", "short_text"
    }:
        value_by_key: Dict[str, Dict[str, Any]] = {}
        display_by_key: Dict[str, List[str]] = {}
        for field in question.fields:
            key = canonical_evidence_key(field.evidence_key)
            if key not in allowed_keys:
                logger.warning(
                    "structured_evidence_field_invalid question_id=%s field_id=%s key=%s",
                    question.question_id,
                    field.field_id,
                    key,
                )
                raise HTTPException(status_code=422, detail="structured_question_unavailable")
            if field.field_id not in request.answer.values:
                continue
            if key not in expected_keys:
                raise HTTPException(status_code=422, detail="structured_question_unavailable")
            answer = request.answer.values[field.field_id]
            if question.control_type in {"boolean", "boolean_group"}:
                if not isinstance(answer, bool):
                    raise HTTPException(status_code=422, detail="boolean answer must be true or false")
                need = need_by_key[key]
                if question.control_type == "boolean_group":
                    if need.evidence_type == "material_status":
                        value = MaterialItemEvidenceValue(
                            requirement_id=question.requirement_id or "",
                            item_id=need.item_id or key.rsplit(".", 1)[-1],
                            material_type=need.material_type,
                            label=need.label,
                            available=answer,
                        ).model_dump()
                    else:
                        item_id = key.rsplit(".", 1)[-1]
                        value = CourseRequirementEvidenceValue(
                            requirement_id=question.requirement_id or "",
                            item_id=item_id,
                            course_name=need.label,
                            completed=answer,
                        ).model_dump()
                    availability: EvidenceAvailability = "known"
                else:
                    if need.other_value_kind == "boolean":
                        controller_binding = controller_bindings_by_key.get(key)
                        if controller_binding is not None:
                            value = ConditionalControllerEvidenceValue(
                                requirement_id=question.requirement_id or "",
                                item_id=need.item_id or key.rsplit(".", 1)[-1],
                                label=need.label,
                                matches_condition=answer,
                                value=(
                                    controller_binding.expected_values[0]
                                    if answer
                                    else None
                                ),
                            ).model_dump()
                            availability = "known" if answer else "known_negative"
                        else:
                            value = OtherItemEvidenceValue(
                                requirement_id=question.requirement_id or "",
                                item_id=need.item_id or key.rsplit(".", 1)[-1],
                                label=need.label,
                                value_kind="boolean",
                                value=answer,
                            ).model_dump()
                            availability = "known"
                    else:
                        value = {"status": answer}
                        availability = "known" if answer else "known_negative"
                submitted[key] = UserEvidence(
                    evidence_type=need.evidence_type,
                    key=key,
                    value=value,
                    raw_answer="有" if answer else "没有",
                    availability=availability,
                    updated_at=now,
                    source_requirement_ids=(
                        [question.requirement_id] if question.requirement_id else []
                    ),
                )
                continue
            if question.control_type in {"number", "number_group"}:
                if isinstance(answer, bool) or not isinstance(answer, (int, float)):
                    raise HTTPException(status_code=422, detail="number answer must be numeric")
                if question.validation.minimum is not None and answer < question.validation.minimum:
                    raise HTTPException(status_code=422, detail="number answer is below the allowed minimum")
                if question.validation.maximum is not None and answer > question.validation.maximum:
                    raise HTTPException(status_code=422, detail="number answer exceeds the allowed maximum")
            elif not isinstance(answer, str) or not answer.strip():
                raise HTTPException(status_code=422, detail="text answer must be a non-empty string")
            value_by_key.setdefault(key, {})
            assign_typed_evidence_path(value_by_key[key], field.value_path, answer)
            display_by_key.setdefault(key, []).append(f"{field.label}: {answer}")
        for key, value in value_by_key.items():
            existing = next(
                (
                    item
                    for item in request.existing_evidence
                    if canonical_evidence_key(item.key) == key
                    and item.availability == "known"
                ),
                None,
            )
            if existing:
                value = merge_evidence_value(existing.value, value)
            need = need_by_key[key]
            if (
                need.evidence_type == "courses"
                and set(need.required_fields) == {"quantity"}
                and need.unit
            ):
                value = CourseCreditEvidenceValue(
                    requirement_id=question.requirement_id or "",
                    label=need.label or "相关课程",
                    quantity=value.get("quantity"),
                    unit=need.unit,
                ).model_dump()
            elif (
                need.evidence_type == "standardized_score"
                and canonical_evidence_key(key) == "gre"
            ):
                value = GREScoreEvidenceValue.model_validate(value).model_dump(
                    exclude_none=True
                )
            elif (
                need.evidence_type == "material_quantity"
                and need.material_type == "recommendation_letters"
            ):
                value = MaterialQuantityEvidenceValue(
                    requirement_id=question.requirement_id or "",
                    item_id=need.item_id or key.rsplit(".", 1)[-1],
                    material_type="recommendation_letters",
                    quantity=value.get("quantity"),
                ).model_dump()
            elif need.other_value_kind in {"numeric", "short_text"}:
                actual_value = value.get(
                    "quantity" if need.other_value_kind == "numeric" else "description"
                )
                value = OtherItemEvidenceValue(
                    requirement_id=question.requirement_id or "",
                    item_id=need.item_id or key.rsplit(".", 1)[-1],
                    label=need.label,
                    value_kind=need.other_value_kind,
                    value=actual_value,
                    options=need.other_options,
                ).model_dump()
            submitted[key] = UserEvidence(
                evidence_type=need.evidence_type,
                key=key,
                value=value,
                raw_answer="；".join(display_by_key[key]),
                availability="known",
                updated_at=now,
                source_requirement_ids=(
                    [question.requirement_id] if question.requirement_id else []
                ),
            )
    elif question.control_type in {"single_select", "multi_select"}:
        selected_values = list(dict.fromkeys(request.answer.selected_options))
        if question.control_type == "single_select" and len(selected_values) != 1:
            raise HTTPException(status_code=422, detail="single_select requires exactly one option")
        minimum = question.validation.min_selections or (1 if question.validation.required else 0)
        if len(selected_values) < minimum:
            raise HTTPException(status_code=422, detail="not enough options were selected")
        if (
            question.validation.max_selections is not None
            and len(selected_values) > question.validation.max_selections
        ):
            raise HTTPException(status_code=422, detail="too many options were selected")
        option_by_value = {option.value: option for option in question.options}
        if any(value not in option_by_value for value in selected_values):
            raise HTTPException(status_code=422, detail="selected option is invalid")
        selected_by_key: Dict[str, List[GapQuestionOption]] = {}
        for value in selected_values:
            option = option_by_value[value]
            key = canonical_evidence_key(option.evidence_key or "")
            if key not in allowed_keys or key not in expected_keys:
                logger.warning(
                    "structured_evidence_option_invalid question_id=%s value=%s key=%s",
                    question.question_id,
                    value,
                    key,
                )
                raise HTTPException(status_code=422, detail="structured_question_unavailable")
            selected_by_key.setdefault(key, []).append(option)
        for key, options in selected_by_key.items():
            mapped_values = [option.evidence_value for option in options]
            if len(options) == 1 and mapped_values[0] is not None:
                value = (
                    mapped_values[0]
                    if isinstance(mapped_values[0], dict)
                    else {"description": mapped_values[0]}
                )
            else:
                value = {
                    "description": "；".join(option.label for option in options),
                    "selected_values": [option.value for option in options],
                }
            need = need_by_key[key]
            if need.other_value_kind in {"single_select", "multi_select"}:
                selected_value: Any = (
                    options[0].value
                    if need.other_value_kind == "single_select"
                    else [option.value for option in options]
                )
                value = OtherItemEvidenceValue(
                    requirement_id=question.requirement_id or "",
                    item_id=need.item_id or key.rsplit(".", 1)[-1],
                    label=need.label,
                    value_kind=need.other_value_kind,
                    value=selected_value,
                    options=need.other_options,
                ).model_dump()
            submitted[key] = UserEvidence(
                evidence_type=need.evidence_type,
                key=key,
                value=value,
                raw_answer="；".join(option.label for option in options),
                availability="known",
                updated_at=now,
            )

    existing_by_key = {
        canonical_evidence_key(item.key): item.model_copy(
            update={"key": canonical_evidence_key(item.key)}
        )
        for item in request.existing_evidence
    }
    combined = {**existing_by_key, **submitted}
    missing_slots, satisfied_groups = structured_evidence_missing_slots(needs, combined)
    slot_states: Dict[str, EvidenceSlotStatus] = {
        slot: "missing" for slot in missing_slots
    }
    for need in needs:
        item = combined.get(need.key)
        if not item:
            continue
        for field in need.required_fields or ["description"]:
            slot = f"{need.key}.{field}"
            if slot not in slot_states:
                slot_states[slot] = item.availability
    return GapEvidenceParseResponse(
        evidence=list(submitted.values()),
        missing_slots=missing_slots,
        follow_up_question=(
            f"还需要补充：{'、'.join(evidence_slot_label(slot) for slot in missing_slots)}。"
            if missing_slots
            else None
        ),
        satisfied_evidence_groups=satisfied_groups,
        slot_states=slot_states,
        parser_calls=0,
    )


@app.post("/gap/evidence/submit", response_model=GapEvidenceParseResponse, tags=["gap"])
async def gap_structured_evidence_endpoint(
    request: GapStructuredEvidenceRequest,
) -> GapEvidenceParseResponse:
    """Validate and store a typed answer without natural-language parsing or LLM calls."""
    return submit_structured_evidence(request)


def evidence_display(item: Optional[UserEvidence]) -> str:
    if item is None:
        return "未提供"
    if item.availability == "unknown":
        return item.raw_answer or "用户明确表示暂时无法提供"
    if item.availability == "known_negative":
        return item.raw_answer or "用户明确表示目前没有"
    if canonical_evidence_key(item.key) in {"ielts", "toefl"} and isinstance(
        item.value, dict
    ):
        test_name = canonical_evidence_key(item.key).upper()
        parts = []
        if item.value.get("score") is not None:
            parts.append(f"{test_name} {item.value['score']:g}")
        subscores = item.value.get("subscores") or {}
        component_values = [
            subscores.get(component) for component in IELTS_COMPONENT_FIELDS
        ]
        if all(value is not None for value in component_values):
            if len(set(component_values)) == 1:
                parts.append(f"四项 {component_values[0]:g}")
            else:
                labels = {
                    "listening": "听力",
                    "reading": "阅读",
                    "writing": "写作",
                    "speaking": "口语",
                }
                parts.extend(
                    f"{labels[component]} {subscores[component]:g}"
                    for component in IELTS_COMPONENT_FIELDS
                )
        if parts:
            return " / ".join(parts)
    return item.raw_answer or str(item.value)


def score_from_evidence(item: UserEvidence) -> tuple[Optional[float], Optional[float], Dict[str, float]]:
    if not isinstance(item.value, dict):
        return None, None, {}
    if (
        item.value.get("value_kind") == "numeric"
        and isinstance(item.value.get("value"), (int, float))
        and not isinstance(item.value.get("value"), bool)
    ):
        return float(item.value["value"]), None, {}
    score = item.value.get("score")
    scale = item.value.get("scale")
    subscores = item.value.get("subscores") or {}
    return (
        float(score) if isinstance(score, (int, float)) else None,
        float(scale) if isinstance(scale, (int, float)) else None,
        {
            str(key): float(value)
            for key, value in subscores.items()
            if isinstance(value, (int, float))
        },
    )


def evaluate_constraint_option(
    option: GapConstraintOption,
    constraint_kind: GapConstraintKind,
    evidence_by_key: Dict[str, UserEvidence],
    importance: RequirementImportance,
) -> tuple[GapStatus, str, str, str]:
    constraint_kind = option.kind or constraint_kind
    item = evidence_by_key.get(canonical_evidence_key(option.key))
    user_text = evidence_display(item)
    if item is None or item.availability == "unknown":
        return "unknown", user_text, "需要补充信息", "当前用户证据不足。"
    if item.availability == "known_negative":
        status: GapStatus = "not_met" if importance == "required" else "partial"
        return status, user_text, "当前尚未具备该项", "用户明确表示目前没有该项证据。"

    if constraint_kind == "score":
        if canonical_evidence_key(option.key) == "gre" and option.component:
            component_score = (
                item.value.get(option.component)
                if isinstance(item.value, dict)
                else None
            )
            if not isinstance(component_score, (int, float)) or option.minimum is None:
                return "unknown", user_text, "需要可比较的 GRE 分项成绩", "GRE 分项数值不足。"
            if component_score < option.minimum:
                difference = round(option.minimum - float(component_score), 2)
                status: GapStatus = "not_met" if importance == "required" else "partial"
                return (
                    status,
                    user_text,
                    f"{option.component} 还差 {difference:g}",
                    "当前 GRE 分项成绩低于明确要求。",
                )
            return "met", user_text, "无", "当前 GRE 分项成绩达到明确要求。"
        score, scale, subscores = score_from_evidence(item)
        if score is None or option.minimum is None:
            return "unknown", user_text, "需要可比较的成绩", "成绩数值不足。"
        if option.scale is not None and (scale is None or abs(scale - option.scale) > 0.001):
            return "unknown", user_text, "分制不可直接比较", "禁止在 GPA 与平均分或不同分制间自动换算。"
        if score < option.minimum:
            difference = round(option.minimum - score, 2)
            status: GapStatus = "not_met" if importance == "required" else "partial"
            return status, user_text, f"还差 {difference:g}", "当前成绩低于明确分数要求。"
        if option.component_minimum is not None:
            below = {
                key: value
                for key, value in subscores.items()
                if value < option.component_minimum
            }
            if below:
                gaps = "、".join(
                    f"{key} 还差 {option.component_minimum - value:g}"
                    for key, value in below.items()
                )
                return "partial", user_text, gaps, "总分达到要求，但已有小分证据显示部分未达到。"
            if len(subscores) < 4:
                return "unknown", user_text, "需要完整小分", "总分已知，但小分信息不足。"
        return "met", user_text, "无", "当前成绩达到明确数值要求。"

    if constraint_kind == "material_boolean":
        available = None
        if isinstance(item.value, dict):
            if item.value.get("value_kind") == "boolean":
                available = item.value.get("value")
            if available is None:
                available = item.value.get("available")
            if available is None:
                available = item.value.get("status")
            if available is None and item.value.get("description") in {
                "有", "是", "已准备", "已具备"
            }:
                available = True
        if available is None and item.raw_answer.strip() in {
            "有", "是", "已准备", "已具备"
        }:
            available = True
        if available is False:
            status: GapStatus = "not_met" if importance == "required" else "partial"
            return status, user_text, "当前缺少该材料", "用户明确表示目前没有该材料。"
        if available is True:
            return "met", user_text, "无", "用户明确表示该材料已经具备。"
        return "unknown", user_text, "需要确认材料是否存在", "材料状态证据不可比较。"
    if constraint_kind == "material_quantity":
        quantity = item.value.get("quantity") if isinstance(item.value, dict) else None
        if (
            quantity is None
            and isinstance(item.value, dict)
            and item.value.get("value_kind") == "numeric"
        ):
            quantity = item.value.get("value")
        if not isinstance(quantity, (int, float)) or option.required_quantity is None:
            return "unknown", user_text, "需要明确数量", "当前数量信息不足。"
        if quantity >= option.required_quantity:
            return "met", user_text, "无", "当前数量达到要求。"
        missing = option.required_quantity - float(quantity)
        status = "not_met" if quantity == 0 and importance == "required" else "partial"
        return status, user_text, f"还需 {missing:g}{option.unit or '项'}", "当前已满足一部分数量要求。"
    if constraint_kind == "course_credit":
        quantity = item.value.get("quantity") if isinstance(item.value, dict) else None
        if not isinstance(quantity, (int, float)) or option.required_quantity is None:
            return "unknown", user_text, "需要明确课程学分", "当前课程学分信息不足。"
        if quantity >= option.required_quantity:
            return "met", user_text, "无", "相关课程学分达到明确要求。"
        missing = option.required_quantity - float(quantity)
        status = "not_met" if importance == "required" else "partial"
        return (
            status,
            user_text,
            f"还差 {missing:g} {option.unit or 'credits'}",
            "相关课程学分尚未达到明确要求。",
        )
    if constraint_kind == "experience_duration":
        has_experience = (
            item.value.get("has_experience")
            if isinstance(item.value, dict)
            else None
        )
        if has_experience is False:
            status: GapStatus = "not_met" if importance == "required" else "partial"
            return status, user_text, "当前没有相关经验", "用户明确表示目前没有相关经验。"
        duration_value = (
            item.value.get("duration") if isinstance(item.value, dict) else None
        )
        if isinstance(duration_value, dict):
            duration = duration_value.get("quantity")
            unit = duration_value.get("unit", "")
        else:
            duration = duration_value
            unit = item.value.get("unit", "") if isinstance(item.value, dict) else ""
        if not isinstance(duration, (int, float)) or option.required_quantity is None:
            return "unknown", user_text, "需要明确经历时长", "当前时长信息不足。"
        months = float(duration) * 12 if str(unit).casefold() in {"年", "year", "years"} else float(duration)
        required_months = option.required_quantity * 12 if option.unit.casefold() in {"year", "years", "年"} else option.required_quantity
        if months >= required_months:
            return "met", user_text, "无", "经历时长达到明确要求。"
        gap_months = required_months - months
        status = "not_met" if importance == "required" else "partial"
        return status, user_text, f"还差约 {gap_months:g} 个月", "经历时长尚未达到要求。"
    return "unknown", user_text, "需要语义判断", "该要求不能仅通过数值规则判断。"


def evaluate_deterministic_requirement(
    planned: GapPlannedRequirement,
    evidence_by_key: Dict[str, UserEvidence],
) -> tuple[GapStatus, str, str, str]:
    constraint = planned.constraint
    if (
        (constraint.kind in {"none", "course_credit"})
        and not any(option.kind for option in constraint.options)
    ) and not planned.course_requirements:
        return "unknown", "未提供", "需要语义判断", "该要求需要语义证据。"
    results = [
        evaluate_constraint_option(
            option,
            constraint.kind,
            evidence_by_key,
            planned.importance,
        )
        for option in constraint.options
    ]
    for course_item in planned.course_requirements:
        item_key = gap_course_item_evidence_key(course_item)
        evidence = evidence_by_key.get(item_key)
        user_text = evidence_display(evidence)
        completed = (
            True
            if course_item.authoritative
            and evidence
            and evidence.availability == "known"
            else False
            if course_item.authoritative
            and evidence
            and evidence.availability == "known_negative"
            else evidence.value.get("completed")
            if evidence
            and isinstance(evidence.value, dict)
            and not course_item.authoritative
            else None
        )
        if not isinstance(completed, bool):
            results.append(
                ("unknown", user_text, f"需确认 {course_item.course_name}", "缺少该必修课程的确认信息。")
            )
        elif completed:
            results.append(("met", user_text, "无", f"用户确认已修读 {course_item.course_name}。"))
        else:
            status: GapStatus = "not_met" if planned.importance == "required" else "partial"
            results.append(
                (status, user_text, f"缺少 {course_item.course_name}", "用户确认尚未修读该课程。")
            )
        if course_item.minimum_credits is not None and course_item.unit:
            credit_key = course_requirement_credit_evidence_key(course_item.item_id)
            credit_evidence = evidence_by_key.get(credit_key)
            quantity = (
                credit_evidence.value.get("quantity")
                if credit_evidence and isinstance(credit_evidence.value, dict)
                else None
            )
            credit_text = evidence_display(credit_evidence)
            if not isinstance(quantity, (int, float)):
                results.append(
                    ("unknown", credit_text, f"需确认 {course_item.course_name} 学分", "缺少该课程的学分信息。")
                )
            elif quantity >= course_item.minimum_credits:
                results.append(("met", credit_text, "无", "该课程学分达到明确要求。"))
            else:
                status = "not_met" if planned.importance == "required" else "partial"
                results.append(
                    (
                        status,
                        credit_text,
                        f"{course_item.course_name} 还差 {course_item.minimum_credits - float(quantity):g} {course_item.unit}",
                        "该课程学分尚未达到明确要求。",
                    )
                )
    if not results:
        return "unknown", "未提供", "需要语义判断", "该要求需要语义证据。"
    if constraint.relation == "any":
        met = next((item for item in results if item[0] == "met"), None)
        if met:
            return met
        if any(item[0] == "unknown" for item in results):
            evidence_text = "；".join(item[1] for item in results)
            return "unknown", evidence_text, "仍有可接受路径信息不足", "尚不能排除其他满足 Requirement 的路径。"
        partial = next((item for item in results if item[0] == "partial"), None)
        return partial or results[0]

    if all(item[0] == "met" for item in results):
        evidence_text = "；".join(item[1] for item in results)
        return "met", evidence_text, "无", "所有明确子要求均已满足。"
    if any(item[0] == "unknown" for item in results):
        evidence_text = "；".join(item[1] for item in results)
        return "unknown", evidence_text, "仍有子要求信息不足", "至少一个必须子项缺少足够信息。"
    if all(item[0] == "not_met" for item in results):
        return results[0]
    evidence_text = "；".join(item[1] for item in results)
    gaps = "；".join(item[2] for item in results if item[0] != "met")
    return "partial", evidence_text, gaps or "部分子要求尚未满足", "部分明确子要求已经满足。"


def combine_gap_status(
    deterministic: GapStatus,
    semantic: GapStatus,
    importance: RequirementImportance,
) -> GapStatus:
    if "unknown" in {deterministic, semantic}:
        return "unknown"
    if "not_met" in {deterministic, semantic}:
        return "not_met" if importance == "required" else "partial"
    if "partial" in {deterministic, semantic}:
        return "partial"
    return "met"


async def batch_semantic_gap_matching(
    tasks: List[Dict[str, Any]],
) -> Dict[str, SemanticGapJudgement]:
    if not tasks:
        return {}
    prompt = (
        "你是 Gap Semantic Matcher。禁止联网，只能比较输入中的 Requirement 与 User Evidence。"
        "不得补充学校要求，不得猜测用户经历。专业相关性、课程等价性、经历相关性和模糊背景"
        "可以语义判断；证据不足必须 unknown。known_negative 是明确没有，unknown 是用户不知道，"
        "两者不能混淆。recommended/preferred 缺失通常为 partial，不按 required 的硬门槛处理。"
        "如果 Requirement 明确接受 closely related discipline，而用户专业经证据判断属于高度相关，"
        "应判 met，不能仅因名称不完全相同就降为 partial。"
        "不要做分数、数量或时长算术。课程含学分时，只返回被语义匹配课程的原始数值到"
        "matched_quantities，求和由代码完成。reason 保持 1-2 句。\n\n"
        f"Tasks：{json.dumps(tasks, ensure_ascii=False)}\n"
        f"输出 JSON Schema：{json.dumps(SemanticGapOutput.model_json_schema(), ensure_ascii=False)}\n"
        "只输出 JSON。"
    )
    content = await call_deepseek(
        messages=[
            {"role": "system", "content": "只输出结构化 Gap judgement，不使用任何工具。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=3500,
        response_format={"type": "json_object"},
    )
    try:
        output = SemanticGapOutput.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned invalid semantic Gap results: {error}",
        ) from error
    return {item.requirement_id: item for item in output.judgements}


def semantic_gap_task_payload(
    planned: GapPlannedRequirement,
    relevant_evidence: List[UserEvidence],
) -> Dict[str, Any]:
    return {
        "requirement_id": planned.requirement_id,
        "category": planned.category,
        "requirement": planned.requirement,
        "importance": planned.importance,
        "user_evidence": [
            {
                "evidence_type": item.evidence_type,
                "key": canonical_evidence_key(item.key),
                "value": item.value,
                "availability": item.availability,
            }
            for item in relevant_evidence
        ],
        "constraint": planned.constraint.model_dump(),
        "temporal_applicability": planned.temporal_applicability,
        "requirement_verification_status": planned.requirement_verification_status,
    }


def planned_evidence_complete(
    planned: GapPlannedRequirement,
    evidence_by_key: Dict[str, UserEvidence],
) -> bool:
    if not planned.evidence_needs:
        return False
    groups: Dict[str, List[GapEvidenceNeed]] = {}
    for need in planned.evidence_needs:
        groups.setdefault(need.evidence_group or planned.requirement_id, []).append(need)
    for needs in groups.values():
        relation = needs[0].group_relation
        evidence_items = [
            (need, evidence_by_key.get(canonical_evidence_key(need.key)))
            for need in needs
        ]
        if relation == "any":
            if any(
                item is not None and evidence_satisfies_need(need, item)
                for need, item in evidence_items
            ):
                continue
            if all(
                item is not None and evidence_is_terminal_for_need(need, item)
                for need, item in evidence_items
            ):
                continue
            return False
        if not all(
            item is not None and evidence_is_terminal_for_need(need, item)
            for need, item in evidence_items
        ):
            return False
    return True


def active_gap_reason_code(status: GapStatus, evidence_complete: bool) -> GapReasonCode:
    if status == "met":
        return "matched"
    if status == "partial":
        return "partially_matched"
    if status == "not_met":
        return "requirement_not_met"
    return (
        "semantic_evidence_insufficient"
        if evidence_complete
        else "user_evidence_missing"
    )


async def analyze_gap(request: GapAnalysisRequest) -> GapAnalysisResponse:
    reusable = merge_reusable_evidence(request.user_profile, request.user_evidence)
    evidence_by_key = {canonical_evidence_key(item.key): item for item in reusable}
    runtime_requirements = [
        item.model_copy(
            update={
                "conditional_state": resolve_conditional_state(item, evidence_by_key)
            }
        )
        for item in request.plan.requirements
    ]
    scope_legacy_material_evidence(runtime_requirements, evidence_by_key)
    evidence_by_key = runtime_course_evidence_view(
        request.target_program,
        runtime_requirements,
        evidence_by_key,
    )
    semantic_tasks = []
    deterministic_results: Dict[str, tuple[GapStatus, str, str, str]] = {}
    informational = []
    temporally_blocked_ids = set()
    conditionally_pending_ids = set()
    conditionally_inactive_ids = set()
    for planned in runtime_requirements:
        if planned.route_scope == "special_internal":
            continue
        if planned.conditional_state == "inactive":
            conditionally_inactive_ids.add(planned.requirement_id)
            continue
        if planned.conditional_state == "pending":
            conditionally_pending_ids.add(planned.requirement_id)
            continue
        if not planned.user_matchable:
            informational.append(planned)
            continue
        if not requirement_is_temporally_matchable(planned.temporal_applicability):
            temporally_blocked_ids.add(planned.requirement_id)
            if planned.match_strategy in {"deterministic", "hybrid"}:
                deterministic_results[planned.requirement_id] = (
                    evaluate_deterministic_requirement(planned, evidence_by_key)
                )
            continue
        if not planned.matchable:
            informational.append(planned)
            continue
        relevant_evidence = [
            evidence_by_key[need.key.casefold()]
            for need in planned.evidence_needs
            if need.key.casefold() in evidence_by_key
        ]
        if planned.match_strategy in {"deterministic", "hybrid"}:
            deterministic_results[planned.requirement_id] = evaluate_deterministic_requirement(
                planned,
                evidence_by_key,
            )
        if planned.match_strategy in {"semantic", "hybrid"}:
            if not relevant_evidence or all(
                item.availability == "unknown" for item in relevant_evidence
            ):
                continue
            semantic_tasks.append(semantic_gap_task_payload(planned, relevant_evidence))

    semantic_results = await batch_semantic_gap_matching(semantic_tasks)
    results = []
    for planned in runtime_requirements:
        if planned.route_scope == "special_internal":
            continue
        if planned.requirement_id in conditionally_inactive_ids:
            continue
        if planned.requirement_id in conditionally_pending_ids:
            controlling_evidence = [
                evidence_by_key[key]
                for key in (
                    canonical_evidence_key(item)
                    for item in planned.conditional.controlling_evidence_keys
                )
                if key in evidence_by_key
            ]
            results.append(
                GapResult(
                    requirement_id=planned.requirement_id,
                    category=planned.category,
                    requirement=planned.requirement,
                    requirement_zh=planned.requirement_zh,
                    requirement_verification_status=(
                        planned.requirement_verification_status
                    ),
                    importance=planned.importance,
                    status="unknown",
                    reason_code="conditional_pending",
                    user_evidence=(
                        "；".join(
                            dict.fromkeys(
                                evidence_display(item)
                                for item in controlling_evidence
                            )
                        )
                        or "适用条件尚未确认"
                    ),
                    gap="适用条件待确认",
                    reason=(
                        "该要求是否适用尚未确定；在条件确认前不执行硬性资格判断。"
                        + (
                            f" 条件：{planned.conditional.condition_text}"
                            if planned.conditional.condition_text
                            else ""
                        )
                    ),
                    source_url=planned.source_url,
                    source_cycle=planned.source_cycle,
                    temporal_applicability=planned.temporal_applicability,
                    temporal_note=planned.temporal_note,
                    conditional_state=planned.conditional_state,
                )
            )
            continue
        if planned.requirement_id in temporally_blocked_ids:
            gap, reason = temporal_gap_explanation(
                planned.temporal_applicability,
                planned.source_cycle,
                planned.temporal_note,
            )
            reference_evidence = [
                evidence_by_key[need.key.casefold()]
                for need in planned.evidence_needs
                if need.key.casefold() in evidence_by_key
            ]
            reference_text = "；".join(
                dict.fromkeys(evidence_display(item) for item in reference_evidence)
            )
            evidence_complete = planned_evidence_complete(planned, evidence_by_key)
            reference_result = deterministic_results.get(planned.requirement_id)
            if planned.temporal_applicability == "previous_cycle":
                reason_code: GapReasonCode = "previous_cycle_reference"
                if reference_result and reference_result[0] == "met":
                    gap = "按上一周期参考要求已满足"
                    reason = f"{reason} 该判断仅作上一周期参考。"
            elif evidence_complete:
                reason_code = "temporal_unconfirmed"
                if reference_result and reference_result[0] == "met":
                    gap = "按当前参考要求已满足，目标周期适用性待确认"
                    reason = f"{reason} 当前用户证据已满足参考条件。"
            elif planned.temporal_applicability == "not_yet_published":
                reason_code = "temporal_unconfirmed"
            else:
                reason_code = "user_evidence_missing"
                gap = "需要补充用户证据；目标周期适用性亦待确认"
            results.append(
                GapResult(
                    requirement_id=planned.requirement_id,
                    category=planned.category,
                    requirement=planned.requirement,
                    requirement_zh=planned.requirement_zh,
                    requirement_verification_status=(
                        planned.requirement_verification_status
                    ),
                    importance=planned.importance,
                    status="unknown",
                    reason_code=reason_code,
                    user_evidence=reference_text or "未执行硬性匹配",
                    gap=gap,
                    reason=reason,
                    source_url=planned.source_url,
                    source_cycle=planned.source_cycle,
                    temporal_applicability=planned.temporal_applicability,
                    temporal_note=planned.temporal_note,
                    conditional_state=planned.conditional_state,
                )
            )
            continue
        if not planned.matchable:
            continue
        deterministic = deterministic_results.get(planned.requirement_id)
        semantic = semantic_results.get(planned.requirement_id)
        if planned.match_strategy == "deterministic":
            status, user_text, gap, reason = deterministic or (
                "unknown", "未提供", "信息不足", "缺少可比较证据。"
            )
        elif planned.match_strategy == "semantic":
            if semantic:
                status, user_text, gap, reason = (
                    semantic.status,
                    semantic.user_evidence,
                    "无" if semantic.status == "met" else semantic.reason,
                    semantic.reason,
                )
            else:
                status, user_text, gap, reason = (
                    "unknown", "用户信息不足", "需要补充信息", "没有足够证据进行语义判断。"
                )
        else:
            deterministic = deterministic or (
                "unknown", "未提供", "信息不足", "缺少确定性证据。"
            )
            if semantic:
                status = combine_gap_status(
                    deterministic[0], semantic.status, planned.importance
                )
                user_text = "；".join(filter(None, (deterministic[1], semantic.user_evidence)))
                gap = deterministic[2] if status != "met" else "无"
                reason = f"{deterministic[3]} {semantic.reason}".strip()
            else:
                status, user_text, gap, reason = deterministic
                if status != "unknown":
                    status = "unknown"
                    gap = "仍需语义相关性判断"
                    reason = "确定性部分已有结果，但语义证据不足。"

        if planned.constraint.kind == "course_credit" and semantic:
            required = next(
                (
                    option.required_quantity
                    for option in planned.constraint.options
                    if option.required_quantity is not None
                ),
                None,
            )
            if required is not None and semantic.matched_quantities:
                total = sum(semantic.matched_quantities)
                status = "met" if total >= required else "partial"
                gap = "无" if status == "met" else f"还差 {required - total:g} 学分/ECTS"
                reason = f"语义匹配课程后由代码合计 {total:g}。"

        results.append(
            GapResult(
                requirement_id=planned.requirement_id,
                category=planned.category,
                requirement=planned.requirement,
                requirement_zh=planned.requirement_zh,
                requirement_verification_status=planned.requirement_verification_status,
                importance=planned.importance,
                status=status,
                reason_code=active_gap_reason_code(
                    status,
                    planned_evidence_complete(planned, evidence_by_key),
                ),
                user_evidence=user_text,
                gap=gap,
                reason=reason,
                source_url=planned.source_url,
                source_cycle=planned.source_cycle,
                temporal_applicability=planned.temporal_applicability,
                temporal_note=planned.temporal_note,
                conditional_state=planned.conditional_state,
            )
        )
    return GapAnalysisResponse(
        target_program=request.target_program,
        results=results,
        informational_requirements=informational,
        semantic_llm_requests=1 if semantic_tasks else 0,
    )


@app.post("/gap/analyze", response_model=GapAnalysisResponse, tags=["gap"])
async def gap_analyze_endpoint(request: GapAnalysisRequest) -> GapAnalysisResponse:
    """Run deterministic checks plus at most one batched semantic LLM request."""
    return await analyze_gap(request)


def precise_calendar_date(value: str) -> Optional[date]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def planning_deadline(
    timeline: ApplicationTimeline,
) -> tuple[Optional[str], Optional[str], Optional[date]]:
    if timeline.status == "not_found" or not timeline.application_deadlines:
        return None, None, None
    precise = [
        (precise_calendar_date(item.date), item)
        for item in timeline.application_deadlines
    ]
    precise = [(parsed, item) for parsed, item in precise if parsed is not None]
    if precise:
        final_dates = [
            pair
            for pair in precise
            if "final" in pair[1].type.casefold()
            or "final" in pair[1].label.casefold()
            or "最终" in pair[1].label
        ]
        parsed, selected = max(final_dates or precise, key=lambda pair: pair[0])
        return selected.date, selected.label, parsed
    selected = next(
        (
            item
            for item in reversed(timeline.application_deadlines)
            if "final" in item.type.casefold()
            or "final" in item.label.casefold()
            or "最终" in item.label
        ),
        timeline.application_deadlines[-1],
    )
    return selected.date, selected.label, None


PLANNING_BUFFER_WEEKS: Dict[str, int] = {
    "language_test_no_valid_score": 20,
    "language_test_retake": 8,
    "standardized_test_no_score": 20,
    "standardized_test_retake": 8,
    "recommendation_letter": 10,
    "portfolio": 6,
    "sop": 4,
    "ps": 4,
    "motivation_letter": 4,
    "writing_sample": 4,
    "cv": 2,
    "resume": 2,
    "transcript": 2,
    "degree_certificate": 2,
    "passport": 2,
    "id_document": 2,
    "generic_material": 2,
    "application_form": 1,
    "application_fee": 1,
}

PLANNING_ACTION_TITLES: Dict[str, str] = {
    "ielts": "取得满足项目要求的 IELTS 成绩",
    "toefl": "取得满足项目要求的 TOEFL 成绩",
    "language_test": "取得满足项目要求的语言考试成绩",
    "standardized_test": "取得满足项目要求的标准化考试成绩",
    "recommendation_letter": "落实项目要求数量的推荐人及推荐信安排",
    "portfolio": "完成 Portfolio 最终版本",
    "sop": "完成 Statement of Purpose 最终版本",
    "ps": "完成 Personal Statement 最终版本",
    "motivation_letter": "完成 Motivation Letter 最终版本",
    "writing_sample": "完成 Writing Sample 最终版本",
    "cv": "完成 CV 最终版本",
    "resume": "完成 Resume 最终版本",
    "transcript": "准备并确认可提交的官方成绩单",
    "degree_certificate": "准备并确认可提交的学位证明",
    "passport": "准备有效护照材料",
    "id_document": "准备有效身份证明材料",
    "application_form": "完成申请表并准备至可提交状态",
    "application_fee": "准备申请费支付",
    "generic_material": "准备并确认可提交的项目要求材料",
}

PLANNING_MATERIAL_RULES: List[tuple[str, str]] = [
    ("recommendation_letter", r"letters? of recommendation|recommendation letters?|reference letters?|\breferences\b|推荐信|推荐人"),
    ("motivation_letter", r"motivation letter|动机信"),
    ("sop", r"statement of purpose|\bsop\b"),
    ("ps", r"personal statement|\bps\b|个人陈述"),
    ("writing_sample", r"writing sample|写作样本"),
    ("transcript", r"transcript|成绩单"),
    ("degree_certificate", r"degree certificate|degree proof|学位证明|学位证"),
    ("portfolio", r"portfolio|work sample|作品集"),
    ("resume", r"\bresume\b|履历"),
    ("cv", r"\bcv\b|curriculum vitae|简历"),
    ("passport", r"passport|护照"),
    ("id_document", r"identification|identity document|\bid\b|身份证明"),
    ("application_form", r"application form|申请表"),
    ("application_fee", r"application fee|申请费"),
]


def planning_gap_text(gap: GapResult) -> str:
    return " ".join(
        part for part in (
            gap.requirement,
            gap.requirement_zh or "",
            gap.user_evidence,
            gap.gap,
            gap.reason,
        ) if part
    ).casefold()


def planning_score_buffer(gap: GapResult, prefix: str) -> Optional[tuple[str, int]]:
    if gap.status == "partial":
        key = f"{prefix}_retake"
        return key, PLANNING_BUFFER_WEEKS[key]
    evidence = gap.user_evidence.casefold().strip()
    if re.search(r"\d+(?:\.\d+)?", evidence):
        key = f"{prefix}_retake"
        return key, PLANNING_BUFFER_WEEKS[key]
    if not evidence or re.search(
        r"未提供|没有|暂无|无有效|no (?:valid )?score|not available|known_negative",
        evidence,
    ):
        suffix = "no_valid_score" if prefix == "language_test" else "no_score"
        key = f"{prefix}_{suffix}"
        return key, PLANNING_BUFFER_WEEKS[key]
    return None


def planning_actionability(gap: GapResult) -> Dict[str, Any]:
    """Classify a Gap only through explicit Planning-owned rules."""
    text = planning_gap_text(gap)
    if gap.status == "met" or gap.conditional_state == "inactive":
        return {"disposition": "skip"}
    if gap.status == "unknown":
        return {
            "disposition": "confirmation",
            "selected_action_kind": "confirm_information",
        }
    if gap.importance != "required":
        return {"disposition": "skip"}

    if gap.category == "academic" and re.search(
        r"major|academic background|degree type|degree classification|\bgpa\b|"
        r"本科专业|学术背景|学位类型|学位等级|平均绩点|最终成绩",
        text,
    ):
        return {"disposition": "eligibility_risk"}
    if gap.category == "course" and re.search(
        r"prerequisite|required course|mandatory course|minimum .*credits?|\bects\b|"
        r"先修|必修|最低.*学分|课程要求",
        text,
    ):
        return {"disposition": "eligibility_risk"}
    if gap.category == "experience" and re.search(
        r"minimum|at least|\d+\s*(?:years?|months?)|最低|至少|年.*经验|个月.*经验",
        text,
    ):
        return {"disposition": "eligibility_risk"}

    action_type: Optional[str] = None
    buffer_key: Optional[str] = None
    buffer_weeks: Optional[int] = None
    if gap.category == "language" or re.search(r"\bielts\b|\btoefl\b|language test|语言考试", text):
        score_buffer = planning_score_buffer(gap, "language_test")
        if score_buffer is None:
            return {"disposition": "confirmation"}
        buffer_key, buffer_weeks = score_buffer
        action_type = "ielts" if "ielts" in text else "toefl" if "toefl" in text else "language_test"
    elif gap.category == "standardized_test" or re.search(
        r"\bgre\b|\bgmat\b|\blsat\b|standardized test|标准化考试", text
    ):
        score_buffer = planning_score_buffer(gap, "standardized_test")
        if score_buffer is None:
            return {"disposition": "confirmation"}
        buffer_key, buffer_weeks = score_buffer
        action_type = "standardized_test"
    else:
        for candidate, pattern in PLANNING_MATERIAL_RULES:
            if re.search(pattern, text):
                action_type = candidate
                break
        if action_type == "portfolio" and re.search(
            r"未提供|没有|暂无|no portfolio|known_negative", gap.user_evidence.casefold()
        ):
            return {"disposition": "confirmation"}
        if action_type is None and gap.category == "materials":
            action_type = "generic_material"
        if action_type is not None:
            buffer_key = action_type
            buffer_weeks = PLANNING_BUFFER_WEEKS[action_type]

    if action_type is None or buffer_key is None or buffer_weeks is None:
        return {"disposition": "confirmation"}
    return {
        "disposition": "action",
        "action_type": action_type,
        "buffer_key": buffer_key,
        "buffer_weeks": buffer_weeks,
        "selected_action_kind": "complete_gap" if gap.status == "partial" else "resolve_gap",
    }


def select_planning_gaps(gaps: List[GapResult]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for gap in gaps:
        classification = planning_actionability(gap)
        if classification["disposition"] == "skip":
            continue
        selected.append({**gap.model_dump(), **classification})
    return selected


def planning_requirement_title(gap: GapResult) -> str:
    title = (gap.requirement_zh or gap.requirement).strip()
    return title if len(title) <= 120 else f"{title[:117]}..."


def planning_action_title(action_type: str, gap: GapResult) -> str:
    text = f"{gap.requirement} {gap.requirement_zh or ''}"
    if action_type == "recommendation_letter":
        quantity = re.search(
            r"(\d+)\s*(?:letters? of recommendation|recommendation letters?|"
            r"reference letters?|封推荐信|位推荐人)",
            text,
            re.IGNORECASE,
        )
        if quantity:
            return f"落实 {quantity.group(1)} 位推荐人及推荐信安排"
    if action_type in {"ielts", "toefl"}:
        score = re.search(
            rf"\b{action_type}\b[^\d]{{0,24}}(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if score:
            return f"取得满足项目要求的 {action_type.upper()} {score.group(1)} 成绩"
    return PLANNING_ACTION_TITLES[action_type]


def validate_action_plan(
    plan: ActionPlan,
    all_gaps: List[GapResult],
    precise_deadline: Optional[date],
    today: date,
) -> None:
    """Validate the code-owned Planning contract; no model contract is involved."""
    gaps_by_id = {gap.requirement_id: gap for gap in all_gaps}
    action_gap_ids = [action.source_gap_id for action in plan.actions]
    if len(action_gap_ids) != len(set(action_gap_ids)):
        raise ValueError("one source_gap_id may produce at most one action")
    all_item_ids = (
        action_gap_ids
        + [item.source_gap_id for item in plan.needs_confirmation]
        + [item.source_gap_id for item in plan.eligibility_risks]
    )
    if len(all_item_ids) != len(set(all_item_ids)):
        raise ValueError("a Gap may belong to only one Planning disposition")
    for gap_id in all_item_ids:
        if gap_id not in gaps_by_id or gaps_by_id[gap_id].status == "met":
            raise ValueError(f"invalid Planning source Gap: {gap_id}")
    for item in plan.needs_confirmation:
        classification = planning_actionability(gaps_by_id[item.source_gap_id])
        if classification["disposition"] != "confirmation" or item.target_date is not None:
            raise ValueError(f"invalid confirmation item: {item.source_gap_id}")
    for item in plan.eligibility_risks:
        if planning_actionability(gaps_by_id[item.source_gap_id])["disposition"] != "eligibility_risk":
            raise ValueError(f"invalid eligibility risk: {item.source_gap_id}")
    for action in plan.actions:
        classification = planning_actionability(gaps_by_id[action.source_gap_id])
        if classification["disposition"] != "action":
            raise ValueError(f"non-actionable Gap produced an action: {action.source_gap_id}")
        if action.action_kind != classification["selected_action_kind"]:
            raise ValueError(f"code-owned action kind mismatch: {action.source_gap_id}")
        if precise_deadline is None:
            if action.target_date is not None or action.timing_status != "priority_only":
                raise ValueError("actions without a reliable Deadline must be priority-only")
        elif action.timing_status == "urgent":
            if action.target_date is not None:
                raise ValueError("urgent actions must not expose a past target date")
        else:
            target = precise_calendar_date(action.target_date or "")
            if target is None or target < today or target > precise_deadline:
                raise ValueError("scheduled target_date must be current/future and no later than Deadline")
    if [action.priority_order for action in plan.actions] != list(range(1, len(plan.actions) + 1)):
        raise ValueError("Planning priority_order must be contiguous and deterministic")
    if precise_deadline is not None:
        seen_scheduled = False
        dated: List[date] = []
        for action in plan.actions:
            if action.timing_status == "urgent":
                if seen_scheduled:
                    raise ValueError("urgent actions must sort before scheduled actions")
            else:
                seen_scheduled = True
                dated.append(date.fromisoformat(action.target_date or ""))
        if dated != sorted(dated):
            raise ValueError("scheduled actions must sort by target_date")


def apply_selected_action_kinds(
    content: DeepSeekActionPlanContent,
    selected_gaps: List[Dict[str, Any]],
) -> DeepSeekActionPlanOutput:
    """Legacy Planning-LLM adapter retained only for old fixture compatibility."""
    selected_by_id = {gap["requirement_id"]: gap for gap in selected_gaps}
    actions: List[PlanningActionDraft] = []
    for action in content.actions:
        selected = selected_by_id.get(action.source_gap_id)
        if selected is None:
            raise HTTPException(
                status_code=502,
                detail=f"Action references unknown Gap: {action.source_gap_id}",
            )
        actions.append(
            PlanningActionDraft(
                **action.model_dump(),
                action_kind=selected["selected_action_kind"],
            )
        )
    return DeepSeekActionPlanOutput(actions=actions)


async def build_action_plan(
    request: ActionPlanRequest,
    *,
    current_date: Optional[date] = None,
) -> ActionPlan:
    today = current_date or date.today()
    deadline_text, deadline_label, exact_deadline = planning_deadline(
        request.application_timeline
    )
    selected_gaps = select_planning_gaps(request.gap_analysis.results)
    common = {
        "target_program": request.target_program,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_date": today.isoformat(),
        "timeline_status": request.application_timeline.status,
        "application_deadline": deadline_text,
        "application_deadline_label": deadline_label,
        "deadline_is_precise": exact_deadline is not None,
        "ready_by_date": None,
        "planning_llm_requests": 0,
    }
    if not selected_gaps:
        return ActionPlan(**common)

    needs_confirmation: List[PlanningConfirmationItem] = []
    eligibility_risks: List[PlanningEligibilityRisk] = []
    action_rows: List[Dict[str, Any]] = []
    gaps_by_id = {gap.requirement_id: gap for gap in request.gap_analysis.results}
    for selected in selected_gaps:
        gap = gaps_by_id[selected["requirement_id"]]
        if selected["disposition"] == "confirmation":
            needs_confirmation.append(
                PlanningConfirmationItem(
                    source_gap_id=gap.requirement_id,
                    title=f"确认：{planning_requirement_title(gap)}",
                    reason=(
                        "当前信息不足，需要尽快确认后再决定后续行动。"
                        if gap.status == "unknown"
                        else "该 required Gap 的可行动性无法由现有明确规则确定，需要进一步确认。"
                    ),
                )
            )
            continue
        if selected["disposition"] == "eligibility_risk":
            eligibility_risks.append(
                PlanningEligibilityRisk(
                    source_gap_id=gap.requirement_id,
                    title=planning_requirement_title(gap),
                    reason="该项可能构成当前申请周期的资格风险，建议确认是否存在例外政策或考虑替代项目。",
                )
            )
            continue

        buffer_weeks = int(selected["buffer_weeks"])
        target = exact_deadline - timedelta(weeks=buffer_weeks) if exact_deadline else None
        urgent = target is not None and target < today
        action_rows.append(
            {
                "source_gap_id": gap.requirement_id,
                "action_type": selected["action_type"],
                "action_kind": selected["selected_action_kind"],
                "buffer_weeks": buffer_weeks,
                "target": None if urgent else target,
                "timing_status": (
                    "urgent" if urgent else "scheduled" if exact_deadline else "priority_only"
                ),
                "gap": gap,
            }
        )

    if exact_deadline:
        action_rows.sort(
            key=lambda row: (
                0 if row["timing_status"] == "urgent" else 1,
                row["target"] or date.max,
                row["source_gap_id"],
            )
        )
    else:
        action_rows.sort(key=lambda row: (-row["buffer_weeks"], row["source_gap_id"]))

    actions: List[PlanningAction] = []
    for priority_order, row in enumerate(action_rows, start=1):
        target = row["target"]
        timing_status: PlanningTimingStatus = row["timing_status"]
        reason = (
            "当前剩余时间已低于建议准备周期，建议立即处理。"
            if timing_status == "urgent"
            else f"按 {row['buffer_weeks']} 周建议准备周期安排；{row['gap'].reason}"
        )
        actions.append(
            PlanningAction(
                action_id=f"planning:{row['source_gap_id']}",
                action=planning_action_title(row["action_type"], row["gap"]),
                action_kind=row["action_kind"],
                time_period=(
                    "立即处理"
                    if timing_status == "urgent"
                    else target.isoformat()
                    if target
                    else f"优先 {priority_order}"
                ),
                target_date=target.isoformat() if target else None,
                source_gap_id=row["source_gap_id"],
                reason=reason,
                status="pending",
                depends_on=[],
                parallel_group=None,
                priority="high" if priority_order <= 3 else "medium",
                requirement_type="required",
                plan_track="main",
                priority_order=priority_order,
                timing_status=timing_status,
            )
        )

    plan = ActionPlan(
        **common,
        needs_confirmation=sorted(needs_confirmation, key=lambda item: item.source_gap_id),
        eligibility_risks=sorted(eligibility_risks, key=lambda item: item.source_gap_id),
        actions=actions,
    )
    validate_action_plan(plan, request.gap_analysis.results, exact_deadline, today)
    return plan


@app.post("/planning/plan", response_model=ActionPlan, tags=["planning"])
async def action_plan_endpoint(request: ActionPlanRequest) -> ActionPlan:
    return await build_action_plan(request)


@app.post("/user-profile", response_model=UserProfile, tags=["profile"])
async def generate_user_profile(request: ProfileRequest) -> UserProfile:
    """Extract a fixed user profile from the six interview answers."""
    empty_profile = UserProfile().model_dump()
    profile_schema = UserProfile.model_json_schema()
    interview_data = [answer.model_dump() for answer in request.answers]
    prompt = (
        "你是留学申请信息整理助手。请仅根据用户提供的六轮访谈内容提取信息，"
        "不要推测、补充或美化任何未提供的信息。缺失的字符串必须填写空字符串，"
        "缺失的列表必须填写空数组。所有数组的每个元素都必须是字符串，不能是对象。"
        "项目、科研和实习要按语义分别归类，不能增加字段。"
        "GPA 与平均成绩必须独立提取，用户只提供一种时另一种保持 null，严禁相互换算。"
        "只返回合法 JSON，不要返回 Markdown 或解释。\n\n"
        f"必须严格使用以下结构：\n{json.dumps(empty_profile, ensure_ascii=False)}\n\n"
        f"JSON Schema：\n{json.dumps(profile_schema, ensure_ascii=False)}\n\n"
        f"访谈内容：\n{json.dumps(interview_data, ensure_ascii=False)}"
    )

    content = await call_deepseek(
        messages=[
            {"role": "system", "content": "你只输出符合指定结构的 JSON 对象。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
        response_format={"type": "json_object"},
    )

    try:
        return UserProfile.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned an invalid user profile: {error}",
        ) from error


TOPIC_RULES: Dict[str, str] = {
    "education": (
        "必须明确本科院校、专业，并至少提供 GPA 或平均成绩之一。"
        "GPA 和平均成绩都分别需要 value 与 scale；不得在两者之间换算。"
    ),
    "courses": "必须提供至少一门相关课程、明确表示没有，或明确表示课程信息无法提供。",
    "projects_research": "必须提供项目/科研/课程设计的任一有效信息、明确表示没有，或明确表示无法提供。其他细节不是必填。",
    "internship": "必须提供实习的任一有效信息（公司/岗位/时间/内容任一）、明确表示没有，或明确表示无法提供。其他细节不是必填。",
    "language": (
        "必须分别确认 IELTS 和 TOEFL 是否有当前可用于申请匹配的数值成绩。"
        "有成绩写 number；没有、未考、备考中、忘记或无法提供都写 null，并标为 unavailable。"
    ),
    "standardized_test": (
        "必须分别确认 GRE 和 GMAT 是否有当前可用于申请匹配的数值成绩。"
        "有成绩写 number；没有、未考、备考中、忘记或无法提供都写 null，并标为 unavailable。"
    ),
}

EXPLICIT_NONE_ANSWERS = {
    "无", "没有", "没", "暂无", "暂时没有", "没有相关课程", "无相关课程",
    "没有项目", "无项目", "没有科研", "无科研", "没有项目科研", "无项目科研",
    "没有实习", "无实习", "没有实习经历", "暂无实习", "暂无实习经历",
    "没考", "没有考", "未考", "未参加", "都没考", "都没有考", "均未参加",
}


def is_explicit_none(answer: str) -> bool:
    """Recognize short, unambiguous negative answers without semantic guessing."""
    normalized = answer.strip().lower()
    for character in "，。！？、,.!?;； ":
        normalized = normalized.replace(character, "")
    return normalized in EXPLICIT_NONE_ANSWERS


def unavailable_exam_score_fields(answer: str, topic: TopicName) -> List[str]:
    """Detect an unavailable score within the clause for a named exam."""
    exams = ("IELTS", "TOEFL") if topic == "language" else ("GRE", "GMAT")
    upper_answer = answer.upper()
    unavailable_words = (
        "不记得", "忘了", "忘记", "不知道", "无法提供", "记不清",
        "没考", "没有考", "未考", "未参加", "备考", "准备", "计划参加",
    )
    unavailable = []
    for exam in exams:
        start = upper_answer.find(exam)
        if start < 0:
            continue
        other_positions = [upper_answer.find(other, start + len(exam)) for other in exams if other != exam]
        valid_positions = [position for position in other_positions if position >= 0]
        end = min(valid_positions) if valid_positions else len(answer)
        clause = answer[start:end]
        if any(word in clause for word in unavailable_words):
            unavailable.append(f"{exam}成绩")
    return unavailable


def apply_explicit_none(profile: UserProfile, topic: TopicName) -> None:
    if topic == "courses":
        profile.education.courses = []
    elif topic == "projects_research":
        profile.experience.projects = []
        profile.experience.research = []
    elif topic == "internship":
        profile.experience.internship = []
    elif topic == "language":
        profile.language.IELTS = None
        profile.language.TOEFL = None
    elif topic == "standardized_test":
        profile.standardized_test.GRE = None
        profile.standardized_test.GMAT = None


def apply_unavailable_fields(
    profile: UserProfile,
    topic: TopicName,
    unavailable_fields: List[str],
    latest_answer: str,
) -> None:
    """Persist explicit inability to provide information in existing profile fields."""
    if topic == "education":
        mapping = {
            "本科院校": "university",
            "专业": "major",
        }
        for field, attribute in mapping.items():
            if field in unavailable_fields and not getattr(profile.education, attribute):
                setattr(profile.education, attribute, "无法提供")
    elif topic == "courses" and unavailable_fields and not profile.education.courses:
        profile.education.courses = ["无法提供"]
    elif topic == "projects_research" and unavailable_fields:
        if not profile.experience.projects and not profile.experience.research:
            labels = "；".join(f"{field}：无法提供" for field in unavailable_fields)
            profile.experience.projects = [f"{latest_answer}；{labels}"]
    elif topic == "internship" and unavailable_fields and not profile.experience.internship:
        labels = "；".join(f"{field}：无法提供" for field in unavailable_fields)
        profile.experience.internship = [f"{latest_answer}；{labels}"]
    elif topic == "language":
        for exam in ("IELTS", "TOEFL"):
            if any(exam in field for field in unavailable_fields):
                setattr(profile.language, exam, None)
    elif topic == "standardized_test":
        for exam in ("GRE", "GMAT"):
            if any(exam in field for field in unavailable_fields):
                setattr(profile.standardized_test, exam, None)


def merge_topic_profile(
    current: UserProfile,
    extracted: UserProfile,
    topic: TopicName,
) -> UserProfile:
    """Apply only the fields owned by the active interview topic."""
    merged = current.model_copy(deep=True)
    if topic == "education":
        merged.education.university = extracted.education.university
        merged.education.major = extracted.education.major
        merged.education.gpa = extracted.education.gpa
        merged.education.average_score = extracted.education.average_score
    elif topic == "courses":
        merged.education.courses = extracted.education.courses
    elif topic == "projects_research":
        merged.experience.projects = extracted.experience.projects
        merged.experience.research = extracted.experience.research
    elif topic == "internship":
        merged.experience.internship = extracted.experience.internship
    elif topic == "language":
        merged.language = extracted.language
    else:
        merged.standardized_test = extracted.standardized_test
    return merged


def required_missing_fields(profile: UserProfile, topic: TopicName) -> List[str]:
    """Enforce deterministic minimum fields where the schema is unambiguous."""
    if topic == "education":
        values = {
            "本科院校": profile.education.university,
            "专业": profile.education.major,
        }
        missing = [name for name, value in values.items() if not value]
        if profile.education.gpa is None and profile.education.average_score is None:
            missing.append("GPA或平均成绩")
            return missing
        for label, score in (
            ("GPA", profile.education.gpa),
            ("平均成绩", profile.education.average_score),
        ):
            if score is None:
                continue
            if score.value is None:
                missing.append(f"{label}数值")
            if score.scale is None:
                missing.append(f"{label}分制")
        return missing
    return []


@app.post("/user-profile/topic", response_model=TopicTurnResponse, tags=["profile"])
async def update_profile_topic(request: TopicTurnRequest) -> TopicTurnResponse:
    """Update one profile topic and decide whether a bounded follow-up is needed."""
    output_example = {
        "profile": request.profile.model_dump(),
        "answer_state": "valid",
        "topic_complete": False,
        "field_states": {"字段中文名称": "missing"},
        "missing_fields": ["缺失字段的中文名称"],
        "follow_up_question": "只针对缺失字段的一句简短中文追问",
    }
    prompt = (
        "你是留学申请背景访谈的信息提取助手。根据当前主题的全部对话，更新 User Profile。"
        "只能使用用户明确提供的信息，不得猜测。不要修改当前主题之外的字段。"
        "所有数组元素必须是字符串。先判断用户最新回答："
        "明确回答“无/没有/没考/暂无”等属于 explicit_none；"
        "能回答当前问题属于 valid；明显无关、无法解释或有歧义属于 ambiguous。"
        "例如询问实习时只回答“博士”，必须判为 ambiguous，不能猜测为某种经历。\n\n"
        "教育成绩必须把 GPA 与平均成绩独立提取：gpa 和 average_score 均为"
        "{value, scale} 或 null。用户只提供一种时另一种保持 null。"
        "严禁根据 GPA 推算平均成绩，也严禁根据平均成绩推算 GPA。"
        "用户没有明确提供分制时，对应 scale 保持 null 并将该分制标为 missing。\n\n"
        "必须为当前主题最低标准涉及的每个字段填写 field_states："
        "known=用户已提供；unavailable=用户明确说忘了、不记得、不知道、记不清或无法提供；"
        "missing=用户尚未回答。只有 missing 才能放入 missing_fields 并追问。"
        "unavailable 不是缺失，不得继续追问；非考试字段在画像对应字符串中写“无法提供”。"
        "只把本主题最低完整标准要求的内容标为 missing，不得把公司、时间等可选细节"
        "擅自升级为必填项。经历类主题只要有任一具体信息就达到最低标准。"
        "例如实习回答“销售，时间和工作内容忘了”，岗位是 known，时间和工作内容是 unavailable，"
        "经历字符串应保留“岗位：销售；时间：无法提供；工作内容：无法提供”，且主题完整。\n\n"
        f"当前主题：{request.topic}\n"
        f"本主题最低完整标准：{TOPIC_RULES[request.topic]}\n"
        "如果达到最低标准，topic_complete=true、missing_fields=[]、follow_up_question为空。"
        "如果未达到，列出最低标准中缺失的字段，并只生成一个合并后的简短追问。"
        "explicit_none 表示当前主题已完成，不要追问。ambiguous 必须 topic_complete=false，"
        "并生成一句中文澄清问题。对于 IELTS、TOEFL、GRE、GMAT，最终画像只能保存"
        "可用于匹配的数值成绩或 null，绝不能保存考试状态文字。"
        "用户给出数值成绩时字段状态为 known；明确没考、没有成绩、备考中、忘记成绩或无法提供时，"
        "字段状态为 unavailable、画像成绩为 null，并且不得追问；只有尚未回答时才标为 missing 并追问。\n\n"
        f"当前画像：{request.profile.model_dump_json()}\n"
        f"本主题对话：{json.dumps([item.model_dump() for item in request.answers], ensure_ascii=False)}\n"
        f"输出示例：{json.dumps(output_example, ensure_ascii=False)}\n"
        f"输出 JSON Schema：{json.dumps(TopicAnalysis.model_json_schema(), ensure_ascii=False)}"
    )

    content = await call_deepseek(
        messages=[
            {"role": "system", "content": "你只输出符合指定结构的 JSON 对象。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1600,
        response_format={"type": "json_object"},
    )

    try:
        analysis = TopicAnalysis.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned an invalid topic analysis: {error}",
        ) from error

    profile = merge_topic_profile(request.profile, analysis.profile, request.topic)
    explicit_none = request.topic != "education" and is_explicit_none(request.answers[-1].answer)
    if explicit_none:
        apply_explicit_none(profile, request.topic)
    unavailable_fields = {
        field for field, state in analysis.field_states.items() if state == "unavailable"
    }
    unavailable_fields.update(
        unavailable_exam_score_fields(request.answers[-1].answer, request.topic)
    )
    for field in unavailable_fields:
        analysis.field_states[field] = "unavailable"
    known_fields = {
        field for field, state in analysis.field_states.items() if state == "known"
    }
    apply_unavailable_fields(
        profile,
        request.topic,
        list(unavailable_fields),
        request.answers[-1].answer,
    )
    deterministic_missing = required_missing_fields(profile, request.topic)
    deterministic_missing = [
        field for field in deterministic_missing if field not in unavailable_fields
    ]
    state_missing = [
        field for field, state in analysis.field_states.items() if state == "missing"
    ]
    reported_missing = [
        field for field in analysis.missing_fields if field not in unavailable_fields
    ]
    if request.topic == "education":
        gpa = profile.education.gpa
        average_score = profile.education.average_score
        if gpa is not None and gpa.value is not None and gpa.scale is not None and average_score is None:
            state_missing = [field for field in state_missing if "平均成绩" not in field]
            reported_missing = [field for field in reported_missing if "平均成绩" not in field]
        if average_score is not None and average_score.value is not None and average_score.scale is not None and gpa is None:
            state_missing = [field for field in state_missing if "GPA" not in field.upper()]
            reported_missing = [field for field in reported_missing if "GPA" not in field.upper()]
    if explicit_none:
        missing_fields = []
    elif analysis.answer_state == "ambiguous":
        missing_fields = ["当前问题的有效回答"]
    else:
        missing_fields = list(
            dict.fromkeys(deterministic_missing or state_missing or reported_missing)
        )
        if request.topic in {"courses", "projects_research", "internship"} and (
            known_fields or unavailable_fields
        ):
            missing_fields = []
    complete = (
        explicit_none
        or (
            analysis.answer_state != "ambiguous"
            and not missing_fields
        )
    )
    limit_reached = not complete and request.follow_up_count >= 2
    follow_up_question = analysis.follow_up_question
    if analysis.answer_state == "ambiguous" and not explicit_none:
        follow_up_question = analysis.follow_up_question or "刚才的回答似乎与当前问题不太相关，可以换一种方式说明吗？"
    if not complete and not follow_up_question:
        follow_up_question = f"还需要补充：{'、'.join(missing_fields)}。"

    return TopicTurnResponse(
        profile=profile,
        complete=complete or limit_reached,
        limit_reached=limit_reached,
        field_states=analysis.field_states,
        missing_fields=missing_fields,
        follow_up_question="" if complete or limit_reached else follow_up_question,
    )
