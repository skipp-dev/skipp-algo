"""Input-surface reduction policy (ENG-WS6-02).

Builds on ENG-WS6-01's surface matrix. Standard users should only
see inputs that drive real product decisions; operator inputs stay
available but visually isolated via display=display.none. This
module declares the policy so the existing pine_input_surface tool
can lint against a stable contract.

DoD:
- Standardnutzer sehen nur produktrelevante Inputs,
- Operator-Inputs bleiben verfuegbar, aber sauber isoliert,
- sichtbare Input-Flaeche ist deutlich kleiner als heute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class InputVisibility(StrEnum):
    USER_VISIBLE = "user_visible"     # produktrelevant; sichtbar
    OPERATOR_ONLY = "operator_only"    # display=display.none verlangt
    EXPERIMENTAL = "experimental"      # display=display.none verlangt
    LEGACY = "legacy"                  # display=display.none verlangt


# Policy table — keyed on the input GROUP label that pine_input_surface
# already extracts. Order is presentation order in docs.
INPUT_GROUP_POLICY: dict[str, InputVisibility] = {
    # User-visible product groups.
    "Hero Surface": InputVisibility.USER_VISIBLE,
    "Action": InputVisibility.USER_VISIBLE,
    "Setup Quality": InputVisibility.USER_VISIBLE,
    "Market Mode": InputVisibility.USER_VISIBLE,
    "Trust": InputVisibility.USER_VISIBLE,
    "Risk": InputVisibility.USER_VISIBLE,
    # Operator-only — must be isolated.
    "Engine": InputVisibility.OPERATOR_ONLY,
    "Diagnostics": InputVisibility.OPERATOR_ONLY,
    "Bus": InputVisibility.OPERATOR_ONLY,
    "Calibration": InputVisibility.OPERATOR_ONLY,
    "Snapshot": InputVisibility.OPERATOR_ONLY,
    "TV Bridge": InputVisibility.OPERATOR_ONLY,
    # Experimental — must be isolated.
    "Experimental": InputVisibility.EXPERIMENTAL,
    "Orderflow Lab": InputVisibility.EXPERIMENTAL,
    # Legacy — must be isolated and is candidate for cleanup.
    "Legacy": InputVisibility.LEGACY,
    "CHoCH Legacy": InputVisibility.LEGACY,
}


VISIBILITIES_REQUIRING_DISPLAY_NONE = (
    InputVisibility.OPERATOR_ONLY,
    InputVisibility.EXPERIMENTAL,
    InputVisibility.LEGACY,
)


@dataclass(frozen=True)
class InputViolation:
    group: str
    label: str
    expected_visibility: InputVisibility
    has_display_none: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "label": self.label,
            "expected_visibility": self.expected_visibility.value,
            "has_display_none": self.has_display_none,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SurfaceVerdict:
    user_visible_count: int
    isolated_count: int
    unknown_group_count: int
    violations: tuple[InputViolation, ...] = field(default_factory=tuple)

    @property
    def passes(self) -> bool:
        return not self.violations and self.unknown_group_count == 0

    def as_dict(self) -> dict:
        return {
            "user_visible_count": self.user_visible_count,
            "isolated_count": self.isolated_count,
            "unknown_group_count": self.unknown_group_count,
            "passes": self.passes,
            "violations": [v.as_dict() for v in self.violations],
        }


def classify_group(group: str | None) -> InputVisibility | None:
    """Return the declared visibility for ``group`` or None if unknown."""
    if not group:
        return None
    return INPUT_GROUP_POLICY.get(group)


def evaluate_inputs(
    inputs: list[dict],
) -> SurfaceVerdict:
    """Evaluate a list of input descriptors against the policy.

    Each input dict must carry ``group``, ``label`` and
    ``has_display_none`` (matching pine_input_surface.InputInfo).
    """
    user_visible = 0
    isolated = 0
    unknown = 0
    violations: list[InputViolation] = []

    for inp in inputs:
        group = inp.get("group")
        label = str(inp.get("label") or "")
        has_dn = bool(inp.get("has_display_none"))
        visibility = classify_group(group)

        if visibility is None:
            unknown += 1
            violations.append(InputViolation(
                group=str(group or ""), label=label,
                expected_visibility=InputVisibility.OPERATOR_ONLY,
                has_display_none=has_dn,
                reason=(f"Gruppe {group!r} ist nicht in INPUT_GROUP_POLICY — "
                        "unbekannte Gruppen blaehen die Nutzeroberflaeche auf."),
            ))
            continue

        if visibility is InputVisibility.USER_VISIBLE:
            user_visible += 1
            if has_dn:
                violations.append(InputViolation(
                    group=str(group), label=label,
                    expected_visibility=visibility,
                    has_display_none=True,
                    reason=("Produktrelevanter Input darf nicht "
                            "display=display.none tragen."),
                ))
            continue

        # Isolated visibility classes must carry display=display.none.
        isolated += 1
        if visibility in VISIBILITIES_REQUIRING_DISPLAY_NONE and not has_dn:
            violations.append(InputViolation(
                group=str(group), label=label,
                expected_visibility=visibility,
                has_display_none=False,
                reason=(f"{visibility.value}-Input muss display=display.none "
                        "tragen — sonst leckt er auf die Nutzeroberflaeche."),
            ))

    return SurfaceVerdict(
        user_visible_count=user_visible,
        isolated_count=isolated,
        unknown_group_count=unknown,
        violations=tuple(violations),
    )
