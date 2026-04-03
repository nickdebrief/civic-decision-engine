from typing import Dict


def derive_system_posture(signals: Dict[str, str]) -> str:
    capability_alignment = signals.get("capability_alignment")
    execution_depth = signals.get("execution_depth")
    pathway_completion = signals.get("pathway_completion")
    surface_to_function_ratio = signals.get("surface_to_function_ratio")
    structural_drift = signals.get("structural_drift")
    parity_integrity = signals.get("parity_integrity")
    observability_strength = signals.get("observability_strength")

    if (
        capability_alignment == "HIGH"
        and execution_depth == "DEEP"
        and pathway_completion == "COMPLETE"
        and parity_integrity == "STRONG"
    ):
        return "STRUCTURALLY_ALIGNED"

    if (
        surface_to_function_ratio == "HIGH"
        and parity_integrity == "SURFACE_LEVEL"
    ):
        return "SURFACE_COMPLETE_RUNTIME_INCOMPLETE"

    if (
        capability_alignment == "LOW"
        and pathway_completion == "INCOMPLETE"
    ):
        return "DECLARED_GREATER_THAN_IMPLEMENTED"

    if (
        observability_strength in {"STRONG", "LIMITED"}
        and execution_depth in {"SHALLOW", "MODERATE"}
    ):
        return "OBSERVABLE_BUT_SHALLOW"

    if (
        pathway_completion == "INCOMPLETE"
        and execution_depth in {"SHALLOW", "MODERATE"}
    ):
        return "PATHWAY_PRESENT_OUTCOME_ABSENT"

    if structural_drift == "ELEVATED":
        return "PARITY_VISUAL_NOT_STRUCTURAL"

    return "PARTIAL_STRUCTURAL_ALIGNMENT"


def derive_structural_finding(signals: Dict[str, str]) -> str:
    capability_alignment = signals.get("capability_alignment")
    execution_depth = signals.get("execution_depth")
    pathway_completion = signals.get("pathway_completion")
    surface_to_function_ratio = signals.get("surface_to_function_ratio")
    parity_integrity = signals.get("parity_integrity")
    hook_coverage = signals.get("hook_coverage")
    observability_strength = signals.get("observability_strength")
    structural_drift = signals.get("structural_drift")

    if surface_to_function_ratio == "HIGH" and parity_integrity == "SURFACE_LEVEL":
        return "Surface parity exceeds runtime capability"

    if capability_alignment == "LOW" and pathway_completion == "INCOMPLETE":
        return "Declared capability exceeds implemented structure"

    if execution_depth == "SHALLOW" and observability_strength in {"WEAK", "LIMITED"}:
        return "Operational depth is limited and weakly evidenced"

    if hook_coverage == "LOW":
        return "Intervention coverage is limited at key boundaries"

    if structural_drift == "ELEVATED":
        return "Structural drift has emerged between presentation and operation"

    return "System structure is only partially aligned with declared form"


def derive_interpretation(signals: Dict[str, str]) -> str:
    capability_alignment = signals.get("capability_alignment")
    execution_depth = signals.get("execution_depth")
    pathway_completion = signals.get("pathway_completion")
    surface_to_function_ratio = signals.get("surface_to_function_ratio")
    parity_integrity = signals.get("parity_integrity")
    observability_strength = signals.get("observability_strength")
    hook_coverage = signals.get("hook_coverage")
    structural_drift = signals.get("structural_drift")

    if surface_to_function_ratio == "HIGH" and parity_integrity == "SURFACE_LEVEL":
        return (
            "The system presents a strong visible structure, but functional depth remains limited. "
            "Similarity is present at the structural level, but operational equivalence is not yet established."
        )

    if capability_alignment == "LOW" and pathway_completion == "INCOMPLETE":
        return (
            "The system declares broader capability than the current structure can reliably support. "
            "Key pathways remain incomplete, which limits confidence in the system’s claimed form."
        )

    if execution_depth == "MODERATE" and observability_strength == "LIMITED":
        return (
            "The system shows some operational substance, but depth remains uneven and visibility is incomplete. "
            "Interpretation should remain cautious."
        )

    if hook_coverage == "LOW":
        return (
            "The system may expose visible pathways, but intervention and control points remain sparse. "
            "This reduces accountability at important boundaries."
        )

    if structural_drift == "ELEVATED":
        return (
            "The system’s presentation has drifted away from its underlying operational condition. "
            "Appearance and function should not be assumed to align."
        )

    return (
        "The system shows partial structural alignment, but its declared form and operational reality "
        "are not yet fully equivalent."
    )


def derive_assessment(signals: Dict[str, str]) -> Dict[str, str]:
    return {
        "system_posture": derive_system_posture(signals),
        "structural_finding": derive_structural_finding(signals),
        "interpretation": derive_interpretation(signals),
    }