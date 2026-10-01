"""Portable, non-executing experiment recipes for R5 planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


_FAMILY_METHODS = {
    "MEMORY-SAFETY": ("sanitizer_or_bounds_probe", "minimal_reproducer", "counterexample_guard"),
    "INJECTION": ("argument_vector_probe", "parser_or_interpreter_boundary", "neutralized_input_control"),
    "RESOURCE-DOS": ("bounded_resource_probe", "rate_or_size_sweep", "cleanup_observation"),
    "RACE": ("barrier_controlled_interleaving", "repeatable_stress_probe", "race_detector_if_available"),
    "STATE": ("state_transition_table", "lifecycle_control_probe", "reset_and_replay"),
    "AUTHN": ("principal_matrix", "authorization_negative_control", "configuration_default_probe"),
    "DATA-INTEGRITY": ("mutation_control_probe", "round_trip_validation", "integrity_boundary_probe"),
    "CRYPTO": ("known_answer_test", "parameter_boundary_probe", "constant_time_claim_review"),
    "WEB": ("request_response_control_pair", "encoding_and_context_probe", "browser_sink_review"),
    "NUMERIC": ("boundary_value_matrix", "overflow_sanitizer_if_available", "sentinel_semantics_check"),
    "ERROR-HANDLING": ("fault_injection", "cleanup_after_failure", "retry_state_probe"),
    "OTHER": ("minimal_reproducer", "negative_control", "impact_boundary_probe"),
}


@dataclass(frozen=True)
class HarnessRecipe:
    recipe_id: str
    language: str
    family: str
    method: str
    prerequisites: tuple[str, ...]
    isolation: str
    fidelity: str
    cleanup: str


class HarnessCatalog:
    def recipes(self, languages: Sequence[str], family: str) -> tuple[HarnessRecipe, ...]:
        family = family.upper()
        methods = _FAMILY_METHODS.get(family, _FAMILY_METHODS["OTHER"])
        return tuple(
            HarnessRecipe(
                recipe_id=f"HARNESS-{language}-{family.lower()}-{index}",
                language=language,
                family=family,
                method=method,
                prerequisites=_prerequisites(language),
                isolation="Campaign-registered temporary directory and process group",
                fidelity="real_target preferred; otherwise label equivalent or mechanism",
                cleanup="record exit status, terminate registered process group, remove registered temp directory",
            )
            for language in sorted(set(languages))
            for index, method in enumerate(methods, start=1)
        )


def _prerequisites(language: str) -> tuple[str, ...]:
    return {
        "c": ("cc or clang", "ASan/UBSan where supported"),
        "cpp": ("c++ or clang++", "ASan/UBSan where supported"),
        "rust": ("rustc/cargo", "sanitizer or Miri where supported"),
        "go": ("go", "-race for concurrency probes"),
        "java": ("JDK", "project test runner"),
        "kotlin": ("JDK and Kotlin compiler",),
        "scala": ("JDK and sbt",),
        "csharp": (".NET SDK",),
        "python": ("python3",),
        "javascript": ("Node.js",),
        "typescript": ("Node.js and TypeScript compiler",),
        "php": ("PHP CLI",),
        "ruby": ("Ruby",),
        "swift": ("Swift toolchain",),
        "shell": ("bash or the declared shell interpreter",),
    }.get(language, ("target-supported runtime or explicit static-only disposition",))


DEFAULT_HARNESS_CATALOG = HarnessCatalog()