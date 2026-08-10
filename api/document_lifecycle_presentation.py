"""Read-only lifecycle episode presentation helpers for Stage 59.

This module groups existing durable evidence for presentation only.  It does
not create Episode 1 rows, resolve publication eligibility, or mutate state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from api.document_lifecycle_events import list_lifecycle_decisions
from api.document_lifecycle_episodes import episode_current_status
from api.document_lifecycle_episodes import list_lifecycle_episodes


ORIGINAL_EPISODE_LABEL = "Original consideration"
RECONSIDERATION_EPISODE_LABEL = "Governed reconsideration"


def _episode_id(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _episode_sequence(episode: dict[str, Any]) -> int:
    try:
        return int(episode.get("episode_sequence") or 0)
    except (TypeError, ValueError):
        return 0


def episode_label(episode_sequence: int, *, public: bool = False) -> str:
    if episode_sequence <= 1:
        return "Original lifecycle" if public else "Episode 1 — Original consideration"
    if public:
        return f"Subsequent governed consideration — Episode {episode_sequence}"
    return f"Episode {episode_sequence} — {RECONSIDERATION_EPISODE_LABEL}"


def build_lifecycle_presentation(
    *,
    item: dict[str, Any],
    decisions: Iterable[dict[str, Any]] = (),
    episodes: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble an observational, disclosure-neutral lifecycle read model."""

    all_decisions = sorted(
        [dict(decision) for decision in decisions],
        key=lambda decision: (
            int(decision.get("decision_sequence") or 0),
            str(decision.get("decided_at") or ""),
            int(decision.get("id") or 0),
        ),
    )
    explicit_episodes = sorted(
        [dict(episode) for episode in episodes],
        key=lambda episode: (
            _episode_sequence(episode),
            str(episode.get("initiated_at") or ""),
            str(episode.get("episode_id") or ""),
        ),
    )
    original_decisions = [
        decision for decision in all_decisions if _episode_id(decision.get("episode_id")) is None
    ]
    grouped_episodes: list[dict[str, Any]] = [
        {
            "sequence": 1,
            "episode_id": None,
            "episode_type": "original",
            "label": episode_label(1),
            "public_label": episode_label(1, public=True),
            "initiated": None,
            "rationale": None,
            "current_status": (
                original_decisions[-1].get("new_status")
                if original_decisions
                else item.get("initial_status") or "pending"
            ),
            "decisions": original_decisions,
        }
    ]
    for episode in explicit_episodes:
        sequence = _episode_sequence(episode)
        episode_id = _episode_id(episode.get("episode_id"))
        scoped = [
            decision for decision in all_decisions
            if _episode_id(decision.get("episode_id")) == episode_id
        ]
        grouped_episodes.append(
            {
                "sequence": sequence,
                "episode_id": episode_id,
                "episode_type": episode.get("episode_type") or "reconsideration",
                "label": episode_label(sequence),
                "public_label": episode_label(sequence, public=True),
                "initiated": episode.get("initiated_at"),
                "initiating_actor": episode.get("initiating_actor"),
                "initiating_actor_role": episode.get("initiating_actor_role"),
                "rationale": episode.get("rationale"),
                "current_status": episode_current_status(episode, all_decisions),
                "decisions": scoped,
            }
        )
    active_episode = None
    for episode in reversed(grouped_episodes[1:]):
        if episode.get("current_status") != "archived":
            active_episode = episode
            break
    current_status = str(item.get("status") or "pending")
    has_reconsideration = bool(explicit_episodes)
    return {
        "current_status": current_status,
        "current_episode": active_episode,
        "current_episode_sequence": active_episode.get("sequence") if active_episode else 1,
        "has_reconsideration": has_reconsideration,
        "public_lifecycle_summary": (
            "Published · Governed reconsideration"
            if has_reconsideration and current_status == "published"
            else "Governed reconsideration"
            if has_reconsideration
            else ""
        ),
        "episodes": grouped_episodes,
    }


def lifecycle_presentation_for_item(
    item: dict[str, Any], *, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Read existing lifecycle evidence for one intake and assemble it."""

    path = db_path or Path(os.getenv("RECORDS_DB_PATH", "records.db"))
    intake_id = str(item.get("intake_id") or "")
    return build_lifecycle_presentation(
        item=item,
        decisions=list_lifecycle_decisions(intake_id=intake_id, db_path=path),
        episodes=list_lifecycle_episodes(intake_id=intake_id, db_path=path),
    )


def episode_context_for_decision(
    decision: dict[str, Any], presentation: dict[str, Any]
) -> dict[str, Any]:
    episode_id = _episode_id(decision.get("episode_id"))
    for episode in presentation.get("episodes", []):
        if _episode_id(episode.get("episode_id")) == episode_id:
            return episode
    return presentation.get("episodes", [{}])[0]


def active_episode_decision(
    presentation: dict[str, Any], *, new_status: str
) -> dict[str, Any] | None:
    active = presentation.get("current_episode")
    if not active:
        candidates = presentation.get("episodes", [{}])[0].get("decisions", [])
    else:
        candidates = active.get("decisions", [])
    matches = [decision for decision in candidates if decision.get("new_status") == new_status]
    return matches[-1] if matches else None
