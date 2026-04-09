from __future__ import annotations

"""Build fast-click recommendations for the recruiter review sidebar."""

from typing import Any, Dict, List, Optional


_IDENTITY_KEYS = {"full_name", "headline", "availability", "region", "email", "phone", "location", "linkedin", "portfolio"}


def _best_block_for_target(target_key: str, detected_blocks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [block for block in detected_blocks if block.get("mapped_field") == target_key]
    if not candidates:
        return None

    def block_score(block: Dict[str, Any]) -> tuple[int, int, int]:
        score = 0
        if block.get("status") == "ready":
            score += 4
        section = (block.get("section") or "").lower()
        title = (block.get("title") or "").lower()
        preview = (block.get("preview") or block.get("content") or "").lower()
        if target_key in _IDENTITY_KEYS:
            if section == "personal_details" or "identity" in title:
                score += 3
            if target_key == "full_name" and len(preview.split()) <= 12:
                score += 1
        elif section in {"raw_unknown", "personal_details"}:
            score -= 2
        else:
            score += 2
        if target_key == "certifications" and any(token in preview for token in ["certificate", "certification", "issuer", "provider", "year", "|"]):
            score += 2
        if target_key == "career_history" and any(token in preview for token in ["responsibil", "employer", "company", "position", "period", "|"]):
            score += 2
        return (score, len(preview), len(block.get("content") or ""))

    best = max(candidates, key=block_score)
    return best if block_score(best)[0] >= 5 else None


def build_recommendations(review_board: Dict[str, Any] | None, detected_blocks: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    if not review_board:
        return []
    detected_blocks = detected_blocks or []
    recommendations: List[Dict[str, Any]] = []
    for item in review_board.get("sections", []):
        if item.get("status") == "Ready":
            continue
        target_key = item.get("key") or ""
        block = _best_block_for_target(target_key, detected_blocks)
        recommendation = {
            "id": f"rec-{target_key}",
            "target_key": target_key,
            "title": item.get("label") or target_key.replace("_", " ").title(),
            "message": item.get("issue") or "Needs review.",
            "action": "apply_block" if block else "focus_field",
            "block_id": block.get("id") if block else None,
            "block_title": block.get("title") if block else None,
            "action_label": "Apply suggestion" if block else "Review field",
            "secondary_label": "Review manually" if block else None,
        }
        recommendations.append(recommendation)
    return recommendations
