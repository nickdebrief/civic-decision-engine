from typing import Dict, List, Any


HIGH_ALIGNMENT_THRESHOLD = 0.80
PARTIAL_ALIGNMENT_THRESHOLD = 0.40

HIGH_HOOK_THRESHOLD = 3
PARTIAL_HOOK_THRESHOLD = 1

STRONG_OBSERVABILITY_THRESHOLD = 4
LIMITED_OBSERVABILITY_THRESHOLD = 2

HIGH_INTERVENTION_THRESHOLD = 4
MEDIUM_INTERVENTION_THRESHOLD = 2


def _safe_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def calculate_capability_alignment(case: Dict[str, Any]) -> str:
    declared = _safe_list(case.get("declared_capabilities"))
    implemented = _safe_list(case.get("implemented_capabilities"))
    missing = _safe_list(case.get("missing_capabilities"))

    declared_count = len(declared)
    implemented_count = len(implemented)
    missing_count = len(missing)

    if declared_count == 0:
        return "LOW"

    coverage_ratio = _ratio(min(implemented_count, declared_count), declared_count)
    missing_ratio = _ratio(missing_count, declared_count)

    if coverage_ratio >= HIGH_ALIGNMENT_THRESHOLD and missing_ratio <= 0.20:
        return "HIGH"
    if coverage_ratio >= PARTIAL_ALIGNMENT_THRESHOLD and missing_ratio <= 1.00:
        return "PARTIAL"
    return "LOW"


def calculate_execution_depth(case: Dict[str, Any]) -> str:
    observed = case.get("observed_components", {})
    commands = _safe_list(observed.get("commands"))
    tools = _safe_list(observed.get("tools"))
    services = _safe_list(observed.get("services"))
    tests = _safe_list(observed.get("tests"))
    hooks = _safe_list(observed.get("hooks"))
    missing = _safe_list(case.get("missing_capabilities"))

    categories_present = sum(
        1 for group in [commands, tools, services, tests] if len(group) > 0
    )

    evidence_depth_score = 0

    if len(commands) > 0:
        evidence_depth_score += 1
    if len(tools) > 0:
        evidence_depth_score += 1
    if len(services) > 0:
        evidence_depth_score += 1
    if len(tests) > 0:
        evidence_depth_score += 1
    if len(hooks) > 0:
        evidence_depth_score += 1

    # Missing capability weight reduces confidence in true depth
    if len(missing) >= 3:
        evidence_depth_score -= 2
    elif len(missing) >= 1:
        evidence_depth_score -= 1

    # Presence across categories matters, but does not alone imply deep runtime
    if categories_present >= 4 and evidence_depth_score >= 4:
        return "DEEP"
    if categories_present >= 2 and evidence_depth_score >= 2:
        return "MODERATE"
    return "SHALLOW"


def calculate_hook_coverage(case: Dict[str, Any]) -> str:
    observed = case.get("observed_components", {})
    hooks = _safe_list(observed.get("hooks"))
    hook_count = len(hooks)

    if hook_count >= HIGH_HOOK_THRESHOLD:
        return "HIGH"
    if hook_count >= PARTIAL_HOOK_THRESHOLD:
        return "PARTIAL"
    return "LOW"


def calculate_observability_strength(case: Dict[str, Any]) -> str:
    observability_points = _safe_list(case.get("observability_points"))
    point_count = len(observability_points)

    if point_count >= STRONG_OBSERVABILITY_THRESHOLD:
        return "STRONG"
    if point_count >= LIMITED_OBSERVABILITY_THRESHOLD:
        return "LIMITED"
    return "WEAK"


def calculate_pathway_completion(case: Dict[str, Any]) -> str:
    declared = _safe_list(case.get("declared_capabilities"))
    missing = _safe_list(case.get("missing_capabilities"))

    if len(declared) == 0:
        return "INCOMPLETE"

    missing_ratio = _ratio(len(missing), len(declared))

    if missing_ratio == 0:
        return "COMPLETE"
    if missing_ratio < 0.5:
        return "PARTIAL"
    return "INCOMPLETE"


def calculate_dependency_fragility(case: Dict[str, Any]) -> str:
    dependencies = _safe_list(case.get("dependency_surface"))
    dependency_count = len(dependencies)

    if dependency_count >= 4:
        return "HIGH"
    if dependency_count >= 2:
        return "MEDIUM"
    return "LOW"


def calculate_surface_to_function_ratio(case: Dict[str, Any]) -> str:
    declared = _safe_list(case.get("declared_capabilities"))
    implemented = _safe_list(case.get("implemented_capabilities"))
    missing = _safe_list(case.get("missing_capabilities"))
    execution_depth = calculate_execution_depth(case)

    declared_count = len(declared)
    implemented_count = len(implemented)
    missing_count = len(missing)

    if declared_count == 0 and implemented_count == 0:
        return "BALANCED"

    if execution_depth == "SHALLOW":
        return "HIGH"

    gap_ratio = _ratio(max(declared_count - min(implemented_count, declared_count), 0), max(declared_count, 1))
    missing_ratio = _ratio(missing_count, max(declared_count, 1))

    if missing_ratio >= 0.5:
        return "HIGH"
    if gap_ratio == 0 and execution_depth == "DEEP" and missing_ratio <= 0.2:
        return "LOW"
    return "BALANCED"


def calculate_intervention_density(case: Dict[str, Any]) -> str:
    intervention_points = _safe_list(case.get("intervention_points"))
    point_count = len(intervention_points)

    if point_count >= HIGH_INTERVENTION_THRESHOLD:
        return "HIGH"
    if point_count >= MEDIUM_INTERVENTION_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def calculate_structural_drift(case: Dict[str, Any]) -> str:
    declared = _safe_list(case.get("declared_capabilities"))
    implemented = _safe_list(case.get("implemented_capabilities"))
    missing = _safe_list(case.get("missing_capabilities"))

    if len(declared) == 0:
        return "LOW"

    drift_ratio = _ratio(
        len(missing) + max(len(declared) - min(len(implemented), len(declared)), 0),
        len(declared) * 2,
    )

    if drift_ratio >= 0.5:
        return "ELEVATED"
    if drift_ratio >= 0.2:
        return "MODERATE"
    return "LOW"


def calculate_parity_integrity(case: Dict[str, Any]) -> str:
    capability_alignment = calculate_capability_alignment(case)
    execution_depth = calculate_execution_depth(case)
    pathway_completion = calculate_pathway_completion(case)
    surface_to_function_ratio = calculate_surface_to_function_ratio(case)

    if (
        capability_alignment == "HIGH"
        and execution_depth == "DEEP"
        and pathway_completion == "COMPLETE"
        and surface_to_function_ratio in {"LOW", "BALANCED"}
    ):
        return "STRONG"

    if (
        capability_alignment in {"HIGH", "PARTIAL"}
        and execution_depth in {"MODERATE", "DEEP"}
        and pathway_completion == "PARTIAL"
        and surface_to_function_ratio in {"BALANCED", "LOW"}
    ):
        return "PARTIAL"

    if surface_to_function_ratio == "HIGH" or execution_depth == "SHALLOW":
        return "SURFACE_LEVEL"

    return "WEAK"


def calculate_all_signals(case: Dict[str, Any]) -> Dict[str, str]:
    return {
        "capability_alignment": calculate_capability_alignment(case),
        "execution_depth": calculate_execution_depth(case),
        "hook_coverage": calculate_hook_coverage(case),
        "observability_strength": calculate_observability_strength(case),
        "pathway_completion": calculate_pathway_completion(case),
        "dependency_fragility": calculate_dependency_fragility(case),
        "surface_to_function_ratio": calculate_surface_to_function_ratio(case),
        "intervention_density": calculate_intervention_density(case),
        "structural_drift": calculate_structural_drift(case),
        "parity_integrity": calculate_parity_integrity(case),
    }