"""
Redrob Data & AI Hackathon — Senior AI Engineer Ranker
3-Gate system: Honeypot Filter → Ghost Filter → CPU Scorer
Processes 100k candidates from a plain JSONL file, outputs top-100 CSV.
"""

import json
import csv
import re
import os
from datetime import datetime, date

# ── Constants ────────────────────────────────────────────────────────────────

DATA_FILE   = r"data\candidates.jsonl"
OUTPUT_FILE = "team_submission.csv"
TOP_N       = 100
CUTOFF_DATE = datetime(2026, 6, 1).date()   # "today" reference; adjust if needed

# Titles that flag a non-technical professional
NON_TECH_TITLES = {"sales", "hr", "marketing", "content"}

# AI skills whose presence on a non-tech profile = keyword stuffer
AI_SKILLS_SET = {
    "rag", "pinecone", "pytorch", "faiss", "langchain", "embeddings",
    "vector search", "llm", "fine-tuning llms", "hugging face transformers",
    "sentence transformers", "mlops", "kubeflow", "mlflow",
    "recommendation systems", "nlp", "information retrieval",
}

# Preferred titles — bonus multiplier applied to base score
TITLE_BONUS = {
    "ml engineer":              1.30,
    "machine learning engineer":1.30,
    "ai engineer":              1.30,
    "nlp engineer":             1.25,
    "applied ml engineer":      1.25,
    "research engineer":        1.20,
    "data scientist":           1.15,
    "data engineer":            1.15,
    "backend engineer":         1.10,
    "software engineer":        1.05,
    "full stack developer":     1.05,
    "recommendation systems engineer": 1.25,
    "search engineer":          1.20,
}

# Core skills with per-skill weights (max contribution capped per skill)
SKILL_WEIGHTS = {
    # Tier-1 AI/ML core
    "python":             3.0,
    "pytorch":            4.0,
    "tensorflow":         3.5,
    "rag":                5.0,
    "embeddings":         4.5,
    "vector search":      4.0,
    "faiss":              4.0,
    "pinecone":           4.0,
    "milvus":             3.5,
    "qdrant":             3.5,
    "langchain":          4.0,
    "llm":                4.5,
    "fine-tuning llms":   4.5,
    "peft":               4.0,
    "lora":               3.5,
    "hugging face transformers": 4.5,
    "sentence transformers":     4.0,
    "nlp":                3.5,
    "mlops":              3.5,
    "mlflow":             3.0,
    "kubeflow":           3.0,
    "recommendation systems": 3.5,
    "information retrieval":  4.0,
    # Data / infra
    "sql":                2.0,
    "spark":              2.0,
    "kafka":              1.5,
    "airflow":            1.5,
    "dbt":                1.5,
    "elasticsearch":      1.5,
    "opensearch":         1.5,
    "bm25":               3.0,
    # ML tooling
    "scikit-learn":       2.5,
    "xgboost":            2.0,
    "lightgbm":           2.0,
    "feature engineering":2.5,
    "prompt engineering": 2.5,
    # Cloud
    "aws":                1.0,
    "gcp":                1.0,
    "azure":              1.0,
    # Bonus specialisations
    "computer vision":    2.0,
    "speech recognition": 2.0,
    "cnn":                2.0,
    "gans":               2.0,
}

PROFICIENCY_MULT = {"expert": 1.4, "advanced": 1.2, "intermediate": 1.0, "beginner": 0.7}

EDU_TIER_BONUS  = {"tier_1": 3.0, "tier_2": 1.5, "tier_3": 0.5, "tier_4": 0.0}

AI_EDU_FIELDS = {
    "artificial intelligence", "machine learning", "data science",
    "computer science", "information technology", "computer engineering",
    "deep learning", "nlp", "statistics",
}


# ── Gate 1: Honeypot / Keyword-Stuffer Filter ─────────────────────────────

# Grace period (months) added to total_exp_months before flagging a skill as impossible.
# 6 months was too tight — candidates with freelance/overlap history were wrongly dropped.
# Raised to 12 months to allow a full year of concurrent / pre-employment skill use.
SKILL_DURATION_GRACE_MONTHS = 12


def gate1_pass(profile: dict, skills: list, cid: str = "", debug: bool = False) -> bool:
    """
    Return False (drop) if candidate fails the honeypot / keyword-stuffer check.

    Rule 1 — Impossible skill duration:
        Any skill whose duration_months > (total_experience_months + GRACE)
        is physically impossible → candidate fabricated or inflated the timeline.

    Rule 2 — Non-tech title + 3 or more AI skills:
        A Sales/HR/Marketing/Content title with a cluster of deep AI skills
        is a classic keyword-stuffer pattern.
    """
    yoe = profile.get("years_of_experience") or 0
    total_exp_months = yoe * 12

    # ── Rule 1: skill duration vs total experience ──────────────────────────
    for sk in skills:
        dur  = sk.get("duration_months") or 0
        name = sk.get("name") or "unknown"
        limit = total_exp_months + SKILL_DURATION_GRACE_MONTHS
        if dur > limit:
            if debug:
                print(
                    f"[G1-DROP] {cid} | skill_duration_mismatch | "
                    f"skill='{name}'  dur={dur}m  >  "
                    f"exp={total_exp_months:.0f}m + grace={SKILL_DURATION_GRACE_MONTHS}m = {limit:.0f}m"
                )
            return False

    # ── Rule 2: non-tech title with AI skill cluster ────────────────────────
    title_lower = (profile.get("current_title") or "").lower()
    is_non_tech = any(word in title_lower for word in NON_TECH_TITLES)
    if is_non_tech:
        cand_skill_names = {(sk.get("name") or "").lower() for sk in skills}
        ai_hit_count = sum(1 for s in cand_skill_names if s in AI_SKILLS_SET)
        if ai_hit_count >= 3:
            if debug:
                matched = [s for s in cand_skill_names if s in AI_SKILLS_SET]
                print(
                    f"[G1-DROP] {cid} | keyword_stuffer | "
                    f"title='{profile.get('current_title')}'  "
                    f"ai_skills_found={matched}"
                )
            return False

    return True


# ── Gate 2: Behavioral "Ghost" Filter ────────────────────────────────────

def gate2_pass(signals: dict) -> bool:
    """Return False (drop) if candidate is behaviorally inactive."""
    response_rate = signals.get("recruiter_response_rate") or 0
    if response_rate < 0.20:
        return False

    last_active_str = signals.get("last_active_date") or ""
    open_to_work    = signals.get("open_to_work_flag", False)

    if last_active_str:
        try:
            last_active = datetime.strptime(last_active_str, "%Y-%m-%d").date()
            months_inactive = (CUTOFF_DATE - last_active).days / 30.0
            if months_inactive > 6 and not open_to_work:
                return False
        except ValueError:
            pass

    return True


# ── Gate 3: Rule-Based Scorer ─────────────────────────────────────────────

def score_candidate(profile: dict, skills: list, signals: dict, certs: list, edu: list) -> float:
    """Compute a deterministic weighted score for a surviving candidate."""

    # — Skill score ─────────────────────────────────────────────────────────
    skill_score = 0.0
    matched_skills = []
    for sk in skills:
        name  = (sk.get("name") or "").lower().strip()
        weight = SKILL_WEIGHTS.get(name, 0.0)
        if weight == 0.0:
            continue
        prof_m = PROFICIENCY_MULT.get((sk.get("proficiency") or "beginner").lower(), 0.7)
        # Endorsements: soft log bonus, max 0.5
        endorsements = min(sk.get("endorsements") or 0, 50)
        endorse_bonus = (endorsements / 50) * 0.5
        skill_score += weight * prof_m + endorse_bonus
        matched_skills.append(name)

    # Skill assessment bonus — verified scores from redrob platform
    assessment_scores = signals.get("skill_assessment_scores") or {}
    assess_bonus = sum(v / 100.0 for v in assessment_scores.values() if isinstance(v, (int, float)) and v > 0)
    skill_score += min(assess_bonus, 3.0)   # cap at 3 pts

    # — Experience score ─────────────────────────────────────────────────────
    yoe = profile.get("years_of_experience") or 0
    # Senior AI Engineer target: 5-12 yrs sweet spot
    if yoe >= 5:
        exp_score = min(yoe, 12) * 1.0      # up to 12 pts
    else:
        exp_score = yoe * 0.5               # penalise < 5 yrs

    # — Title score ──────────────────────────────────────────────────────────
    title_lower   = (profile.get("current_title") or "").lower()
    title_mult    = 1.0
    for t, m in TITLE_BONUS.items():
        if t in title_lower:
            title_mult = max(title_mult, m)
            break

    # — Education score ──────────────────────────────────────────────────────
    edu_score = 0.0
    for e in edu:
        tier  = (e.get("tier") or "tier_4").lower()
        field = (e.get("field_of_study") or "").lower()
        edu_score += EDU_TIER_BONUS.get(tier, 0.0)
        if any(f in field for f in AI_EDU_FIELDS):
            edu_score += 1.5

    edu_score = min(edu_score, 6.0)     # cap

    # — Certification bonus ──────────────────────────────────────────────────
    cert_score = min(len(certs) * 0.5, 2.0)

    # — Behavioral signals ───────────────────────────────────────────────────
    github_raw = signals.get("github_activity_score") or -1
    github_bonus = max(github_raw, 0) / 100 * 3.0   # max 3 pts; -1 → 0

    completeness = (signals.get("profile_completeness_score") or 0) / 100 * 2.0  # max 2 pts

    response_rate = signals.get("recruiter_response_rate") or 0
    rr_bonus = response_rate * 2.0      # max ~2 pts for rr=1.0

    # — Base score ───────────────────────────────────────────────────────────
    base = (skill_score + exp_score + edu_score + cert_score + github_bonus + completeness + rr_bonus) * title_mult

    # — Behavioral multiplier (interview completion rate) ────────────────────
    icr = signals.get("interview_completion_rate") or 0
    final_score = base * max(icr, 0.1)  # floor at 0.1 to avoid zeroing good candidates

    return round(final_score, 4)


# ── Reasoning builder ─────────────────────────────────────────────────────

def build_reasoning(profile: dict, skills: list, signals: dict) -> str:
    title = profile.get("current_title") or "Unknown"
    yoe   = profile.get("years_of_experience") or 0
    icr   = signals.get("interview_completion_rate") or 0
    rr    = signals.get("recruiter_response_rate") or 0

    matched = [sk.get("name") for sk in skills if (sk.get("name") or "").lower() in SKILL_WEIGHTS and SKILL_WEIGHTS[(sk.get("name") or "").lower()] >= 3.0]
    top_skills = ", ".join(matched[:3]) if matched else "general skills"

    return (f"{title} with {yoe:.1f} yrs exp; top skills: {top_skills}; "
            f"interview rate: {icr:.0%}; recruiter response: {rr:.0%}.")


# ── Main pipeline ─────────────────────────────────────────────────────────

def main(debug_drops: bool = False):
    """
    Main pipeline.
    Set debug_drops=True (or run with --debug) to print a drop-reason line
    for every candidate rejected by Gate 1 or Gate 2.
    """
    candidates_scored = []
    total = dropped_g1 = dropped_g2 = 0

    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            total += 1

            try:
                rec = json.loads(raw_line)
            except json.JSONDecodeError:
                dropped_g1 += 1
                if debug_drops:
                    print(f"[G1-DROP] line {total} | json_parse_error")
                continue

            cid     = rec.get("candidate_id", f"UNKNOWN_{total}")
            profile = rec.get("profile") or {}
            skills  = rec.get("skills") or []
            signals = rec.get("redrob_signals") or {}
            certs   = rec.get("certifications") or []
            edu     = rec.get("education") or []

            # Gate 1 — pass cid and debug flag so drop reasons are printed
            if not gate1_pass(profile, skills, cid=cid, debug=debug_drops):
                dropped_g1 += 1
                continue

            # Gate 2
            if not gate2_pass(signals):
                dropped_g2 += 1
                if debug_drops:
                    rr  = signals.get('recruiter_response_rate', 'n/a')
                    la  = signals.get('last_active_date', 'n/a')
                    otw = signals.get('open_to_work_flag', False)
                    print(f"[G2-DROP] {cid} | recruiter_response_rate={rr}  last_active={la}  open_to_work={otw}")
                continue

            # Gate 3 — score
            score = score_candidate(profile, skills, signals, certs, edu)
            candidates_scored.append((cid, score, profile, skills, signals))

    # Sort descending, take top 100
    candidates_scored.sort(key=lambda x: x[1], reverse=True)
    top100 = candidates_scored[:TOP_N]

    # Write CSV
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        for rank, (cid, score, profile, skills, signals) in enumerate(top100, start=1):
            reasoning = build_reasoning(profile, skills, signals)
            writer.writerow([cid, rank, score, reasoning])

    print(f"Done. Processed: {total} | Dropped G1: {dropped_g1} | Dropped G2: {dropped_g2} | "
          f"Scored: {len(candidates_scored)} | Written: {len(top100)}")
    print(f"Output: {os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    import sys
    # Pass --debug as a CLI argument to see per-candidate drop reasons:
    #   python main.py --debug
    debug = "--debug" in sys.argv
    main(debug_drops=debug)
