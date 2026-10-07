"""Safety instructions for workers (UC-15).

Every safety rule publishes one instruction for its location, so workers
assigned there see the rule and can acknowledge it like any instruction an
officer writes.  The instruction is removed together with its rule.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from sqlalchemy.orm import Session

import models
from services.notification_service import notify_instruction_published


PPE_ITEM_LABELS = {"Helmet": "Helmet", "Safety Vest": "Safety Vest", "Gloves": "Gloves"}
ALL_PPE_LABELS = ["Helmet", "Safety Vest", "Gloves"]


def rule_details(rule: models.SafetyRule, location_name: str) -> Dict[str, object]:
    """Title, text and structured guidance shown to workers for one rule."""

    if rule.is_restricted_area:
        return {
            "title": f"Restricted Area: Do Not Enter {location_name}",
            "description": (
                f"{location_name} is a restricted area. Nobody may enter, with or without PPE. "
                "Cameras report anyone seen there as a violation."
            ),
            "category": "hazards",
            "warnings": ["No worker is authorized to enter this location."],
            "dos": ["Stay out of this restricted area", "Report attempted entry to a safety officer"],
            "donts": ["Do not enter this area", "Do not attempt work inside this zone"],
            "equipment": [],
        }
    if rule.ppe_type == "No PPE":
        return {
            "title": f"No PPE Required at {location_name}",
            "description": f"No personal protective equipment is required at {location_name}.",
            "category": "ppe",
            "warnings": [],
            "dos": [],
            "donts": [],
            "equipment": [],
        }
    items = ALL_PPE_LABELS if rule.ppe_type == "All PPE" else [PPE_ITEM_LABELS.get(rule.ppe_type, rule.ppe_type)]
    requirement = "Full PPE" if rule.ppe_type == "All PPE" else rule.ppe_type
    return {
        "title": f"{requirement} Required at {location_name}",
        "description": (
            f"Mandatory safety rule for {location_name}: wear {', '.join(items).lower()} at all times. "
            "Cameras check this automatically."
        ),
        "category": "ppe",
        "warnings": [],
        "dos": [f"Must wear {item}" for item in items],
        "donts": ["Do not remove PPE inside this location"],
        "equipment": items,
    }


def _location_name(db: Session, location_id: int) -> str:
    location = db.get(models.Location, location_id)
    return location.name if location else "Assigned Location"


def publish_rule_instruction(db: Session, rule: models.SafetyRule, created_by: int = None, notify: bool = True) -> models.SafetyInstruction:
    details = rule_details(rule, _location_name(db, rule.location_id))
    instruction = models.SafetyInstruction(
        location_id=rule.location_id,
        created_by=created_by,
        title=details["title"],
        content=details["description"],
        category=details["category"],
        safety_rule_id=rule.id,
    )
    db.add(instruction)
    db.flush()
    if notify:
        notify_instruction_published(db, instruction)
    return instruction


def ensure_rule_instructions(db: Session, location_ids: Iterable[int]) -> int:
    """Publish instructions for rules created before rules published them."""

    location_ids = list(location_ids)
    if not location_ids:
        return 0
    rules = (
        db.query(models.SafetyRule)
        .outerjoin(models.SafetyInstruction, models.SafetyInstruction.safety_rule_id == models.SafetyRule.id)
        .filter(
            models.SafetyRule.location_id.in_(location_ids),
            models.SafetyInstruction.id.is_(None),
        )
        .all()
    )
    for rule in rules:
        publish_rule_instruction(db, rule, notify=False)
    if rules:
        db.commit()
    return len(rules)


def instruction_view(instruction: models.SafetyInstruction) -> Dict[str, List[str]]:
    """Structured guidance: rule-derived when linked to a rule, else empty."""

    if instruction.rule is not None:
        location_name = instruction.location.name if instruction.location else "Assigned Location"
        details = rule_details(instruction.rule, location_name)
        return {key: details[key] for key in ("warnings", "dos", "donts", "equipment")}
    return {"warnings": [], "dos": [], "donts": [], "equipment": []}
