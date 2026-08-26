from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar, get_args
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError, field_validator

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

QS_RANKINGS_DB = BACKEND_DIR / "data" / "rankings" / "qs_rankings.sqlite"
QS_SUBJECTS_FILE = BACKEND_DIR / "data" / "rankings" / "qs_subjects.json"
TARGET_PROGRAM_CONFIRMATION_TIMEOUT_SECONDS = 30.0
REQUIREMENTS_TOTAL_TIMEOUT_SECONDS = 120.0
TIMELINE_TOTAL_TIMEOUT_SECONDS = 120.0
WEB_SEARCH_TIMEOUT_SECONDS = 180.0
SCHOOL_URL_BATCH_SIZE = 12

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

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


FieldInformationState = Literal["known", "unavailable", "missing"]


class Language(BaseModel):
    IELTS: Optional[float] = None
    TOEFL: Optional[float] = None


class StandardizedTest(BaseModel):
    GRE: Optional[float] = None
    GMAT: Optional[float] = None


class UserProfile(BaseModel):
    education: Education = Field(default_factory=Education)
    experience: Experience = Field(default_factory=Experience)
    language: Language = Field(default_factory=Language)
    standardized_test: StandardizedTest = Field(default_factory=StandardizedTest)


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
    ranking_subject: Optional[str] = None
    additional_preferences: str = ""
    intended_entry_year: int = Field(
        default_factory=lambda: datetime.now(timezone.utc).year + 1,
        ge=2026,
        le=2100,
    )
    intended_entry_term: Literal["fall", "spring", "summer", "winter"] = "fall"


class QSSubjectMappingRequest(BaseModel):
    target_major: str = Field(min_length=1)


class QSSubjectMappingResult(BaseModel):
    target_major: str
    candidates: List[str] = Field(default_factory=list)


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
    intended_entry_year: int = Field(
        default_factory=lambda: datetime.now(timezone.utc).year + 1,
        ge=2026,
        le=2100,
    )
    intended_entry_term: Literal["fall", "spring", "summer", "winter"] = "fall"


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


class RequirementsExtraction(BaseModel):
    requirements: List[RequirementItem] = Field(default_factory=list)


class RequirementCategoryReview(BaseModel):
    category: RequirementCategory
    coverage: RequirementCoverage
    requirements: List[RequirementItem] = Field(default_factory=list)


class TargetProgramRequirementsReview(BaseModel):
    target_program: TargetProgram
    checked_at: str
    categories: List[RequirementCategoryReview]


EvidenceAvailability = Literal["known", "known_negative", "unknown"]
GapStatus = Literal["met", "partial", "not_met", "unknown"]
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
    "generic",
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
    label: str = ""
    already_known: bool = False

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


class GapDeterministicConstraint(BaseModel):
    kind: GapConstraintKind = "none"
    relation: Literal["all", "any"] = "all"
    options: List[GapConstraintOption] = Field(default_factory=list)


class GapPlannerRequirementDraft(BaseModel):
    requirement_id: str
    matchable: bool
    informational_reason: str = ""
    match_strategy: GapMatchStrategy = "semantic"
    evidence_needs: List[GapEvidenceNeed] = Field(default_factory=list)
    constraint: GapDeterministicConstraint = Field(
        default_factory=GapDeterministicConstraint
    )


class GapPlannerQuestion(BaseModel):
    question_id: str
    question: str = Field(min_length=1)
    evidence_keys: List[str] = Field(min_length=1)


class GapPlannerOutput(BaseModel):
    requirements: List[GapPlannerRequirementDraft] = Field(default_factory=list)
    questions: List[GapPlannerQuestion] = Field(default_factory=list)


class GapPlannedRequirement(GapPlannerRequirementDraft):
    category: RequirementCategory
    requirement: str
    requirement_zh: Optional[str] = None
    importance: RequirementImportance
    requirement_verification_status: Literal[
        "official_verified", "model_memory_unverified", "user_supplied"
    ]
    source_url: Optional[str] = None


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


class GapEvidenceParseRequest(BaseModel):
    question: GapPlannerQuestion
    evidence_needs: List[GapEvidenceNeed]
    answer: str = Field(min_length=1)


class GapEvidenceParseResponse(BaseModel):
    evidence: List[UserEvidence]


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
    status: GapStatus
    user_evidence: str
    gap: str
    reason: str
    source_url: Optional[str] = None


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


async def call_deepseek(
    messages: List[Dict[str, str]],
    max_tokens: int,
    response_format: Optional[Dict[str, str]] = None,
) -> str:
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

    content = response.choices[0].message.content
    if not content:
        raise HTTPException(status_code=502, detail="DeepSeek API returned an empty response")
    return content


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


@app.get("/rankings/qs/subjects", tags=["rankings"])
async def list_qs_subjects() -> Dict[str, Any]:
    """Return the locally imported, official QS Subject taxonomy."""
    return load_qs_subject_taxonomy()


@app.post(
    "/rankings/qs/map-subject",
    response_model=QSSubjectMappingResult,
    tags=["rankings"],
)
async def map_target_major_to_qs_subject(
    request: QSSubjectMappingRequest,
) -> QSSubjectMappingResult:
    """Map a user's major to one to three names from the local QS taxonomy."""
    target_major = request.target_major.strip()
    if not target_major:
        raise HTTPException(status_code=422, detail="target_major must not be blank")

    allowed_subjects = list(qs_subject_records())
    mapping_prompt = (
        "将用户目标专业映射到最相关的 QS 学科。你只能从 allowed_subjects 原样选择名称，"
        "禁止翻译、改写或创造名称。明显唯一匹配时返回 1 个；存在合理歧义时返回 2 到 3 个，"
        "按相关性从高到低排序。只输出 JSON。\n\n"
        f"target_major：{target_major}\n"
        f"allowed_subjects：{json.dumps(allowed_subjects, ensure_ascii=False)}\n"
        f"输出结构：{json.dumps(QSSubjectMappingResult(target_major=target_major).model_dump(), ensure_ascii=False)}\n"
        f"JSON Schema：{json.dumps(QSSubjectMappingResult.model_json_schema(), ensure_ascii=False)}"
    )
    content = await call_deepseek(
        messages=[
            {
                "role": "system",
                "content": "你是受控分类器，只能从用户提供的候选列表中选择值并输出 JSON。",
            },
            {"role": "user", "content": mapping_prompt},
        ],
        max_tokens=350,
        response_format={"type": "json_object"},
    )
    try:
        mapped = QSSubjectMappingResult.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned invalid QS Subject mapping data: {error}",
        ) from error

    allowed_set = set(allowed_subjects)
    candidates: List[str] = []
    for subject in mapped.candidates:
        if subject in allowed_set and subject not in candidates:
            candidates.append(subject)
        if len(candidates) == 3:
            break
    if not candidates:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek did not return a valid Subject from the local QS taxonomy",
        )
    return QSSubjectMappingResult(target_major=target_major, candidates=candidates)


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


@app.post(
    "/candidate-universities/discover",
    response_model=CandidateUniversityResult,
    tags=["programs"],
)
async def discover_candidate_universities(
    target: ExploreTargetRequest,
) -> CandidateUniversityResult:
    """Filter the locally imported QS rankings without any external API call."""
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
        ranking_subject = (target.ranking_subject or "").strip()
        subject_record = qs_subject_records().get(ranking_subject)
        if subject_record is None:
            raise HTTPException(
                status_code=422,
                detail="ranking_subject must be an exact Subject from the local QS taxonomy",
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
    return CandidateUniversityResult(
        universities=await enrich_school_official_urls(universities)
    )


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


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
        text = "\n".join(
            str(item.get("text") or "")
            for item in output
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
        if not text:
            raise ValueError("response did not contain a final text block")
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


@app.post(
    "/candidate-programs/discover",
    response_model=CandidateProgramResult,
    tags=["programs"],
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
        intended_entry_year=request.intended_entry_year,
        intended_entry_term=request.intended_entry_term,
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
            }
        ]
    }
    prompt = (
        "Use Web Search to produce a useful application Requirements snapshot for this exact "
        "master's programme. Your task is not limited to reporting requirements whose full "
        "official page text is currently accessible. For each of the seven categories "
        "academic, course, language, standardized_test, experience, materials, and other, "
        "apply this priority: current official source first; otherwise a reasonable "
        "best-effort AI reference; otherwise no item for that category.\n\n"
        "First search, open, read, and judge relevant current programme, department, and "
        "university pages. When you have a reasonable current official source, use "
        "source_type=official_retrieval, verification_status=official_verified, and include "
        "its source_url. These internal values mean product status official_source.\n\n"
        "If an official page is blocked by 403/WAF, inaccessible, incomplete, available only "
        "through a search-result summary, or insufficient to confirm a category, do not "
        "automatically omit that category. Continue best-effort within this same task using "
        "the information available to you: other searches, result summaries, other public "
        "pages, and your existing knowledge. When that produces a reasonable reference, use "
        "source_type=model_memory and verification_status=model_memory_unverified. These "
        "internal compatibility values mean product status ai_reference; they do not imply "
        "that the information came only from training memory. Use source_level=unknown. A "
        "reference URL may be retained when useful, but it does not upgrade the item to an "
        "official source. Use source_url=null when no reliable reference URL is available.\n\n"
        "Keep the research phase short: use no more than two Web Search calls. Complete only "
        "the necessary searches, then immediately output the final structured JSON; do not "
        "continue searching for exhaustive coverage. If official information remains "
        "inaccessible or incomplete, stop searching and use the existing ai_reference "
        "mechanism with your reasonable available information and existing knowledge. "
        "Prioritize returning one complete final JSON object over further research. You must "
        "finish with final JSON even when the result is sparse.\n\n"
        "The product explicitly accepts cautious planning references when a current official "
        "fact cannot be confirmed. If you know a plausible or commonly reported requirement "
        "for the programme, institution, degree type, or closely related application process, "
        "prefer a carefully qualified AI reference (for example using may, typically, or "
        "applicants should check) over immediately omitting the category. Mark it as "
        "model_memory_unverified, normally use importance=unknown, and never present it as a "
        "confirmed current fact. This applies especially when you have useful planning "
        "information about academic background, language expectations, or application "
        "materials, but it does not require filling categories you genuinely know nothing "
        "about.\n\n"
        "Only omit a category when you have neither usable official information nor a "
        "reasonable AI reference. Do not invent an answer merely to fill all seven categories, "
        "and do not infer that something is not required merely because it was not mentioned. "
        "Return at most twelve concise requirements. Preserve every score, threshold, "
        "exception, and AND/OR condition. Return both the English requirement and a faithful "
        "concise Chinese requirement_zh in this same response. For AI references, use "
        "importance=unknown unless the requirement's modality is reasonably known.\n\n"
        "Do not narrate the research process, search steps, access failures, or reasoning. "
        "Do not explain the result. Finish the final JSON promptly and return only one JSON "
        "object shaped exactly like this example:\n"
        f"{json.dumps(output_example, ensure_ascii=False)}\n\n"
        f"Target programme: {json.dumps(target_program.model_dump(), ensure_ascii=False)}"
    )
    extraction = await call_deepseek_web_search(
        prompt,
        RequirementsExtraction,
        schema_name="program_requirements",
        max_output_tokens=7000,
        max_search_uses=2,
    )
    return requirements_review_from_extraction(target_program, extraction)


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
) -> TargetProgramRequirementsReview:
    try:
        return await asyncio.wait_for(
            retrieve_target_program_requirements(target_program),
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
        "source, return null or omit the deadline.\n\n"
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


@app.post(
    "/target-programs/timeline",
    response_model=ApplicationTimeline,
    tags=["programs"],
)
async def target_program_timeline_endpoint(
    request: ApplicationTimelineRequest,
) -> ApplicationTimeline:
    try:
        return await asyncio.wait_for(
            retrieve_application_timeline(request),
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
    for key, score in (
        ("ielts", profile.language.IELTS),
        ("toefl", profile.language.TOEFL),
        ("gre", profile.standardized_test.GRE),
        ("gmat", profile.standardized_test.GMAT),
    ):
        if score is not None:
            evidence_type: GapEvidenceType = (
                "language_score" if key in {"ielts", "toefl"} else "standardized_score"
            )
            add(evidence_type, key, {"score": score, "scale": None}, str(score))
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


def merge_reusable_evidence(
    profile: UserProfile,
    user_evidence: List[UserEvidence],
) -> List[UserEvidence]:
    merged: Dict[str, UserEvidence] = {
        item.key.casefold(): item for item in profile_user_evidence(profile)
    }
    for item in user_evidence:
        merged[item.key.casefold()] = item
    return list(merged.values())


def formal_gap_requirements(
    review: TargetProgramRequirementsReview,
) -> List[Dict[str, Any]]:
    formal = []
    for category in review.categories:
        for index, requirement in enumerate(category.requirements):
            if requirement.verification_status not in {
                "official_verified",
                "model_memory_unverified",
                "user_supplied",
            }:
                continue
            formal.append(
                {
                    "requirement_id": f"{category.category}:{index}",
                    "category": category.category,
                    "requirement": requirement.requirement,
                    "requirement_zh": requirement.requirement_zh,
                    "importance": requirement.importance,
                    "requirement_verification_status": requirement.verification_status,
                    "source_url": requirement.source_url,
                }
            )
    return formal


async def build_gap_plan(request: GapPlanRequest) -> GapPlan:
    formal_requirements = formal_gap_requirements(request.requirements_review)
    reusable = merge_reusable_evidence(request.user_profile, request.user_evidence)
    if not formal_requirements:
        return GapPlan(
            target_program=request.target_program,
            reusable_evidence=reusable,
            planning_llm_requests=0,
        )

    evidence_summary = [item.model_dump() for item in reusable]
    output_schema = GapPlannerOutput.model_json_schema()
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
        "gpa、average_score、ielts、toefl、gre、gmat、courses、experience、"
        "materials.portfolio、materials.cv、materials.transcript、materials.degree_certificate、"
        "materials.recommendations。不要把项目名写入 evidence key。\n"
        "evidence_type 只能从 education_university、education_major、academic_score、"
        "language_score、standardized_score、courses、material_status、material_quantity、"
        "experience、generic 中选择，不得输出其他值。\n"
        "constraint.kind 仅允许 score、material_boolean、material_quantity、"
        "experience_duration、course_credit、none。IELTS/TOEFL OR 关系放在同一个 constraint.options；"
        "constraint.relation：所有选项都要满足用 all，任一考试路径满足即可用 any。"
        "同一条 Requirement 同时含材料是否具备和数量时，在每个 option.kind 分别填写"
        "material_boolean 或 material_quantity，外层 kind 可用 none。"
        "GPA 与 average_score 必须分别使用自己的 key，禁止换算。"
        "只能解析 Requirement 原文明示的数字、考试替代路径和材料数量：referee/references 的复数"
        "不等于两封；未明确数量的推荐信/支持材料必须按 material_boolean 询问是否已准备，"
        "不能追问或判断具体数量。B2 也不能自行创造 IELTS/TOEFL 分数等价关系。"
        "原文未给阈值时保持 null。"
        "推荐信数量、材料是否准备、考试阈值由代码计算，不能让后续 LLM 做算术。\n"
        "所有面向用户的 question 必须使用简洁自然的中文。问题应合并相关 Evidence，"
        "例如一次询问所有相关课程，不要逐门课程机械提问。"
        "已有 evidence 的 availability 无论 known、known_negative 还是 unknown，都代表已经回答，"
        "不得重复提问。不允许为 informational Requirement 生成问题。\n\n"
        f"Target Program：{request.target_program.model_dump_json()}\n"
        f"正式 Requirements：{json.dumps(formal_requirements, ensure_ascii=False)}\n"
        f"已有可复用 Evidence：{json.dumps(evidence_summary, ensure_ascii=False)}\n"
        f"输出 JSON Schema：{json.dumps(output_schema, ensure_ascii=False)}\n"
        "只输出 JSON，不要解释。"
    )
    content = await call_deepseek(
        messages=[
            {"role": "system", "content": "你只输出严格符合 schema 的 JSON，不使用任何工具。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4500,
        response_format={"type": "json_object"},
    )
    try:
        draft = GapPlannerOutput.model_validate_json(content)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek returned an invalid Gap Plan: {error}",
        ) from error

    formal_by_id = {item["requirement_id"]: item for item in formal_requirements}
    draft_by_id = {
        item.requirement_id: item
        for item in draft.requirements
        if item.requirement_id in formal_by_id
    }
    known_keys = {item.key.casefold() for item in reusable}
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
        normalized_needs = []
        for need in item.evidence_needs:
            normalized = need.model_copy(
                update={"already_known": need.key.casefold() in known_keys}
            )
            normalized_needs.append(normalized)
            if item.matchable:
                needs_by_key[need.key.casefold()] = normalized
        match_strategy = item.match_strategy
        option_kinds = {option.kind for option in item.constraint.options if option.kind}
        if formal["category"] == "materials" and (
            item.constraint.kind in {"material_boolean", "material_quantity"}
            or option_kinds
            and option_kinds <= {"material_boolean", "material_quantity"}
        ):
            match_strategy = "deterministic"
        elif formal["category"] in {
            "academic", "language", "standardized_test"
        } and item.constraint.kind == "score":
            match_strategy = "deterministic"
        planned.append(
            GapPlannedRequirement(
                **formal,
                matchable=item.matchable,
                informational_reason=item.informational_reason,
                match_strategy=match_strategy,
                evidence_needs=normalized_needs,
                constraint=item.constraint,
            )
        )

    questions = []
    covered_missing_keys = set()
    ai_reference_keys = {
        need.key.casefold()
        for item in planned
        if item.requirement_verification_status == "model_memory_unverified"
        for need in item.evidence_needs
    }
    for question in draft.questions:
        missing_keys = [
            key
            for key in question.evidence_keys
            if key.casefold() in needs_by_key
            and key.casefold() not in known_keys
        ]
        if not missing_keys:
            continue
        question_text = question.question
        if (
            any(key.casefold() in ai_reference_keys for key in missing_keys)
            and "AI 参考" not in question_text
            and "AI参考" not in question_text
        ):
            question_text = f"根据目前的 AI 参考信息，该项目可能有相关要求。{question_text}"
        questions.append(
            question.model_copy(
                update={
                    "question": question_text,
                    "evidence_keys": missing_keys,
                }
            )
        )
        covered_missing_keys.update(key.casefold() for key in missing_keys)

    for item in planned:
        if not item.matchable:
            continue
        missing_needs = [
            need
            for need in item.evidence_needs
            if not need.already_known
            and need.key.casefold() not in covered_missing_keys
        ]
        if not missing_needs:
            continue
        labels = "、".join(need.label or need.key for need in missing_needs)
        question_prefix = (
            "根据目前的 AI 参考信息，该项目可能有这项要求。"
            if item.requirement_verification_status == "model_memory_unverified"
            else ""
        )
        question = GapPlannerQuestion(
            question_id=f"q:{item.requirement_id}",
            question=(
                f"{question_prefix}为了判断“{item.requirement}”，请补充：{labels}。"
                "不知道或暂时没有也可以直接说明。"
            ),
            evidence_keys=[need.key for need in missing_needs],
        )
        questions.append(question)
        covered_missing_keys.update(need.key.casefold() for need in missing_needs)

    return GapPlan(
        target_program=request.target_program,
        requirements=planned,
        questions=questions,
        reusable_evidence=reusable,
        planning_llm_requests=1,
    )


@app.post("/gap/plan", response_model=GapPlan, tags=["gap"])
async def gap_plan_endpoint(request: GapPlanRequest) -> GapPlan:
    """Plan one adaptive evidence interview without Web Search."""
    return await build_gap_plan(request)


UNKNOWN_ANSWER_MARKERS = (
    "不知道", "不记得", "忘了", "忘记", "不确定", "无法提供", "记不清",
)
NEGATIVE_ANSWER_MARKERS = (
    "没有", "没考", "未考", "没修过", "未修过", "没学过", "未学过", "没上过", "未上过",
    "未准备", "还没准备", "暂无", "暂时没有", "没有准备", "无",
)


def evidence_answer_clause(answer: str, key: str) -> str:
    aliases_by_key = {
        "ielts": ("ielts", "雅思"),
        "toefl": ("toefl", "托福"),
        "gre": ("gre",),
        "gmat": ("gmat",),
        "gpa": ("gpa",),
        "average_score": ("average", "平均分", "均分"),
        "portfolio": ("portfolio", "作品集"),
        "recommendations": ("recommend", "推荐信", "推荐人"),
        "statement_of_purpose": ("statement of purpose", "personal statement", "sop", "个人陈述", "动机信"),
        "cv": ("cv", "简历"),
        "transcript": ("transcript", "成绩单"),
        "degree_certificate": ("degree certificate", "diploma", "学位证", "学历证明", "毕业证"),
    }
    lowered = answer.casefold()
    aliases = next(
        (values for marker, values in aliases_by_key.items() if marker in key.casefold()),
        (),
    )
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


def parse_evidence_value(key: str, answer: str) -> Any:
    lowered_key = key.casefold()
    if lowered_key == "gpa" and not re.search(r"\bgpa\b", answer, re.IGNORECASE):
        if re.search(r"平均分|均分|average", answer, re.IGNORECASE):
            return None
    score_keys = ("gpa", "average_score", "ielts", "toefl", "gre", "gmat")
    if any(marker in lowered_key for marker in score_keys):
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
        return {
            "score": float(overall_match.group(1)) if overall_match else numbers[0],
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


def parse_gap_evidence(request: GapEvidenceParseRequest) -> GapEvidenceParseResponse:
    now = datetime.now(timezone.utc).isoformat()
    evidence = []
    need_by_key = {need.key.casefold(): need for need in request.evidence_needs}
    for key in request.question.evidence_keys:
        need = need_by_key.get(key.casefold())
        if need is None:
            continue
        clause = (
            request.answer
            if len(request.question.evidence_keys) == 1
            else evidence_answer_clause(request.answer, key)
        ).strip()
        if any(marker in clause.casefold() for marker in UNKNOWN_ANSWER_MARKERS):
            availability: EvidenceAvailability = "unknown"
        elif any(marker in clause.casefold() for marker in NEGATIVE_ANSWER_MARKERS) or clause.strip() == "0":
            availability = "known_negative"
        else:
            availability = "known"
        value = parse_evidence_value(key, clause) if availability == "known" else None
        if availability == "known" and value is None:
            availability = "unknown"
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
    return GapEvidenceParseResponse(evidence=evidence)


@app.post("/gap/evidence/parse", response_model=GapEvidenceParseResponse, tags=["gap"])
async def gap_evidence_parse_endpoint(
    request: GapEvidenceParseRequest,
) -> GapEvidenceParseResponse:
    """Parse one answer locally; this endpoint never calls an LLM."""
    return parse_gap_evidence(request)


def evidence_display(item: Optional[UserEvidence]) -> str:
    if item is None:
        return "未提供"
    if item.availability == "unknown":
        return item.raw_answer or "用户明确表示暂时无法提供"
    if item.availability == "known_negative":
        return item.raw_answer or "用户明确表示目前没有"
    return item.raw_answer or str(item.value)


def score_from_evidence(item: UserEvidence) -> tuple[Optional[float], Optional[float], Dict[str, float]]:
    if not isinstance(item.value, dict):
        return None, None, {}
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
    item = evidence_by_key.get(option.key.casefold())
    user_text = evidence_display(item)
    if item is None or item.availability == "unknown":
        return "unknown", user_text, "需要补充信息", "当前用户证据不足。"
    if item.availability == "known_negative":
        status: GapStatus = "not_met" if importance == "required" else "partial"
        return status, user_text, "当前尚未具备该项", "用户明确表示目前没有该项证据。"

    if constraint_kind == "score":
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
        return "met", user_text, "无", "用户明确表示该材料已经具备。"
    if constraint_kind == "material_quantity":
        quantity = item.value.get("quantity") if isinstance(item.value, dict) else None
        if not isinstance(quantity, (int, float)) or option.required_quantity is None:
            return "unknown", user_text, "需要明确数量", "当前数量信息不足。"
        if quantity >= option.required_quantity:
            return "met", user_text, "无", "当前数量达到要求。"
        missing = option.required_quantity - float(quantity)
        status = "not_met" if quantity == 0 and importance == "required" else "partial"
        return status, user_text, f"还需 {missing:g}{option.unit or '项'}", "当前已满足一部分数量要求。"
    if constraint_kind == "experience_duration":
        duration = item.value.get("duration") if isinstance(item.value, dict) else None
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
    ) or not constraint.options:
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


async def analyze_gap(request: GapAnalysisRequest) -> GapAnalysisResponse:
    reusable = merge_reusable_evidence(request.user_profile, request.user_evidence)
    evidence_by_key = {item.key.casefold(): item for item in reusable}
    semantic_tasks = []
    deterministic_results: Dict[str, tuple[GapStatus, str, str, str]] = {}
    informational = []
    for planned in request.plan.requirements:
        if not planned.matchable:
            informational.append(planned)
            continue
        relevant_evidence = [
            evidence_by_key[need.key.casefold()].model_dump()
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
                item["availability"] == "unknown" for item in relevant_evidence
            ):
                continue
            semantic_tasks.append(
                {
                    "requirement_id": planned.requirement_id,
                    "category": planned.category,
                    "requirement": planned.requirement,
                    "importance": planned.importance,
                    "user_evidence": relevant_evidence,
                    "constraint": planned.constraint.model_dump(),
                }
            )

    semantic_results = await batch_semantic_gap_matching(semantic_tasks)
    results = []
    for planned in request.plan.requirements:
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
                status=status,
                user_evidence=user_text,
                gap=gap,
                reason=reason,
                source_url=planned.source_url,
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
