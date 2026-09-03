from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import main as application


def profile(**material_updates) -> application.UserProfile:
    materials = application.ApplicationMaterials(**material_updates)
    return application.UserProfile(
        education=application.Education(
            university="University X",
            major="Computer Science",
            gpa=application.ScoreWithScale(value=3.6, scale=4.0),
        ),
        language=application.Language(
            IELTS=7.5,
            IELTS_status="has_value",
            IELTS_subscores={
                "listening": 7.5,
                "reading": 7.5,
                "writing": 7.0,
                "speaking": 7.0,
            },
        ),
        standardized_test=application.StandardizedTest(
            GRE=None,
            GRE_status="none",
            GMAT=None,
            GMAT_status="unknown",
        ),
        materials=materials,
    )


def by_key(profile_value: application.UserProfile):
    return {
        application.canonical_evidence_key(item.key): item
        for item in application.profile_user_evidence(profile_value)
    }


def cv_result(evidence_by_key, importance="required"):
    return application.evaluate_constraint_option(
        application.GapConstraintOption(key="materials.cv"),
        "material_boolean",
        evidence_by_key,
        importance,
    )


def run() -> None:
    positive = profile(
        cv_status="prepared",
        transcript_status="prepared",
        degree_certificate_status="prepared",
        motivation_letter_status="prepared",
        portfolio_status="not_prepared",
        confirmed_recommenders=2,
    )
    facts = by_key(positive)
    assert facts["materials.cv"].availability == "known"
    assert facts["materials.cv"].value["available"] is True
    assert cv_result(facts)[0] == "met"
    print("PASS CV prepared maps to positive Gap fact")

    negative_facts = by_key(profile(cv_status="not_prepared"))
    assert negative_facts["materials.cv"].availability == "known_negative"
    assert cv_result(negative_facts)[0] == "not_met"
    print("PASS CV not prepared maps to explicit negative")

    missing_profile = profile(cv_status=None)
    stale_legacy_negative = application.UserEvidence(
        evidence_type="material_status",
        key="materials.cv",
        value={"available": False},
        raw_answer="没有",
        availability="known_negative",
        updated_at="2026-01-01T00:00:00Z",
    )
    merged_missing = {
        item.key: item
        for item in application.merge_reusable_evidence(missing_profile, [])
    }
    assert "materials.cv" not in merged_missing
    assert cv_result(merged_missing)[0] == "unknown"
    print("PASS missing CV stays unknown without fabricated negative evidence")

    assert facts["materials.recommendations"].value["quantity"] == 2
    assert facts["materials.recommendations"].availability == "known"
    print("PASS recommender count preserves 2")

    assert facts["materials.transcript"].value["available"] is True
    assert facts["materials.transcript"].availability == "known"
    print("PASS transcript prepared maps positive")

    degree_certificate = facts["materials.degree_certificate"]
    assert degree_certificate.value["available"] is True
    assert degree_certificate.availability == "known"
    assert application.evaluate_constraint_option(
        application.GapConstraintOption(key="materials.degree_certificate"),
        "material_boolean",
        facts,
        "required",
    )[0] == "met"
    print("PASS degree certificate prepared reaches existing material comparator")

    unknown_degree_certificate = by_key(
        profile(degree_certificate_status="unknown")
    )["materials.degree_certificate"]
    assert unknown_degree_certificate.availability == "unknown"
    assert application.evaluate_constraint_option(
        application.GapConstraintOption(key="materials.degree_certificate"),
        "material_boolean",
        {"materials.degree_certificate": unknown_degree_certificate},
        "required",
    )[0] == "unknown"
    print("PASS degree certificate unknown remains unknown")

    assert facts["materials.personal_statement"].value["available"] is True
    assert facts["materials.personal_statement"].availability == "known"
    print("PASS SOP/motivation letter maps positive")

    assert facts["materials.portfolio"].value["available"] is False
    assert facts["materials.portfolio"].availability == "known_negative"
    print("PASS portfolio not prepared remains negative")

    assert facts["ielts"].value["score"] == 7.5
    assert facts["ielts"].value["subscores"]["listening"] == 7.5
    print("PASS IELTS score and subscores reach normalized facts")

    assert facts["gpa"].value == {"score": 3.6, "scale": 4.0}
    print("PASS GPA value and scale reach normalized facts")

    assert facts["education.university"].value == "University X"
    assert facts["education.major"].value == "Computer Science"
    assert facts["gre"].availability == "known_negative"
    assert facts["gmat"].availability == "unknown"
    print("PASS education and standardized-test terminal states map correctly")

    stale_scoped_negative = application.UserEvidence(
        evidence_type="material_status",
        key="material_item.old-cv",
        value={"material_type": "cv", "available": False},
        raw_answer="没有",
        availability="known_negative",
        updated_at="2026-01-01T00:00:00Z",
    )
    merged_positive = {
        item.key: item
        for item in application.merge_reusable_evidence(
            positive, [stale_legacy_negative, stale_scoped_negative]
        )
    }
    assert merged_positive["materials.cv"].value["available"] is True
    assert "material_item.old-cv" not in merged_positive
    print("PASS Standard Profile is authoritative over legacy interview evidence")

    scoped_cv_key = "material_item.materials-0-cv"
    scoped_cv_need = application.GapEvidenceNeed(
        key=scoped_cv_key,
        evidence_type="material_status",
        value_kind="boolean",
        label="CV / Resume",
        material_type="cv",
        item_id="materials-0-cv",
    )
    scoped_cv_requirement = application.GapPlannedRequirement(
        requirement_id="materials:0",
        matchable=True,
        match_strategy="deterministic",
        evidence_needs=[scoped_cv_need],
        constraint=application.GapDeterministicConstraint(
            kind="material_boolean",
            options=[application.GapConstraintOption(key=scoped_cv_key)],
        ),
        category="materials",
        requirement="A CV is required.",
        importance="required",
        requirement_verification_status="official_verified",
        temporal_applicability="undated",
    )
    application.scope_legacy_material_evidence(
        [scoped_cv_requirement], merged_positive
    )
    assert merged_positive[scoped_cv_key].value["available"] is True
    assert application.evaluate_deterministic_requirement(
        scoped_cv_requirement, merged_positive
    )[0] == "met"
    print("PASS canonical CV fact reaches requirement-scoped deterministic Gap")

    unknown_material = by_key(profile(cv_status="unknown"))["materials.cv"]
    assert unknown_material.availability == "unknown"
    assert cv_result({"materials.cv": unknown_material})[0] == "unknown"
    print("PASS explicit uncertainty is not converted to not_met")

    print("PASS Standard Profile -> Gap mapping regressions")


if __name__ == "__main__":
    run()
