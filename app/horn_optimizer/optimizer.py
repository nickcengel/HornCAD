"""Restartable, measured multi-round BEM optimizer."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable, Iterable

import yaml

from app.design_api import DesignIntent, RoundControlHeuristics
from app.tools.run_bem_search import (
    export_candidate_stl,
    geometry_feasibility,
    materialize_candidate,
    run_search,
)
from app.tools.run_stage_aware_bem_queue import run_queue

from .schema import HornOptimizerConfig, NumericRange


ROOT = Path(__file__).resolve().parents[2]
HEURISTICS = ROOT / "models/round_control_heuristics_v1"
TRANSFER_RESULTS = ROOT / "examples/non-round-transfer-study/results.json"
BASE_PROJECT = (
    ROOT / "examples/control-decoupling/searches/core-axis/40deg/350x350"
    / "candidates/candidate-000/project.yaml"
)
STATE_NAME = "optimizer_state.json"
REPORT_NAME = "index.html"
COORDINATE_FIELDS = (
    "mouth_width_mm", "mouth_height_mm", "length_mm", "extension_mm",
    "k_h", "k_v", "n_h", "n_v", "sag_mm",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    temporary.replace(path)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def _normalized_number(value: float) -> float:
    return float(f"{float(value):.9f}")


def coordinate_payload(
    config: HornOptimizerConfig, values: dict[str, float],
) -> dict[str, Any]:
    return {
        "intent": {
            "horizontal_coverage_deg": config.horizontal_coverage_deg,
            "vertical_coverage_deg": config.vertical_coverage_deg,
            "throat_angle_deg": config.throat_angle_deg,
            "mouth_shape": config.mouth_shape,
            "sag_axes": config.sag_axes,
        },
        "values": {
            key: _normalized_number(values[key])
            for key in COORDINATE_FIELDS
        },
    }


def coordinate_hash(
    config: HornOptimizerConfig, values: dict[str, float],
) -> str:
    return _hash(coordinate_payload(config, values))


def proposal_hash(
    coordinate: str, round_number: int, branch: str,
    parent_hash: str | None = None,
) -> str:
    return _hash({
        "coordinate_hash": coordinate,
        "round": round_number,
        "branch": branch,
        "parent_hash": parent_hash,
    })


def rank_measurements(
    rows: Iterable[dict[str, Any]],
    *,
    shortlist_points: float = 0.5,
    tie_break: str = "throat_impedance",
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """Rank measured rows by the versioned surface/impedance contract."""
    measured = [
        row for row in rows
        if row.get("status") in {"complete", "reused"}
        and row.get("surface_score_v2_3") is not None
    ]
    if not measured:
        return []
    best_surface = max(float(row["surface_score_v2_3"]) for row in measured)
    shortlist = [
        row for row in measured
        if best_surface-float(row["surface_score_v2_3"])
        <= shortlist_points+1e-9
    ]
    if not enabled or tie_break == "surface_only":
        return sorted(
            measured,
            key=lambda row: (
                -float(row["surface_score_v2_3"]),
                row["coordinate_hash"],
            ),
        )
    shortlist_ids = {id(row) for row in shortlist}
    return sorted(
        measured,
        key=lambda row: (
            0 if id(row) in shortlist_ids else 1,
            -float(row.get("throat_impedance_score_v2_3_0", -math.inf))
            if id(row) in shortlist_ids else
            -float(row["surface_score_v2_3"]),
            -float(row["surface_score_v2_3"]),
            row["coordinate_hash"],
        ),
    )


def _range_contains(bounds: NumericRange, value: float) -> bool:
    return bounds.minimum-1e-9 <= value <= bounds.maximum+1e-9


def _shape_squareness(shape: str) -> float:
    return 1.0 if shape == "square" else 0.0


def _sag_flags(axes: str) -> tuple[bool, bool]:
    return axes in {"horizontal", "both"}, axes in {"vertical", "both"}


def _project_values(document: dict[str, Any]) -> dict[str, float]:
    config = document["horncad_config"]
    global_config = config["global"]
    horizontal = config["horizontal_basis"]
    vertical = config["vertical_basis"]
    return {
        "mouth_width_mm": float(global_config["mouth_width"]),
        "mouth_height_mm": float(global_config["mouth_height"]),
        "length_mm": float(global_config["length"]),
        "extension_mm": float(
            global_config.get("conical_extension_length", 0)),
        "k_h": float(horizontal["k"]),
        "k_v": float(vertical["k"]),
        "n_h": float(horizontal["n"]),
        "n_v": float(vertical["n"]),
        "sag_mm": float(global_config.get("mouth_sag", 0)),
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(
            value.get("horncad_config"), dict):
        raise ValueError(f"not a HornCAD project YAML: {path}")
    return value


def _transfer_length_rule() -> str:
    if not TRANSFER_RESULTS.is_file():
        return "width-height-weighted"
    result = _read_json(TRANSFER_RESULTS)
    rule = result.get("promotion", {}).get("common_length_rule", "weighted")
    return (
        "s-balanced" if str(rule) == "s-balanced"
        else "width-height-weighted"
    )


def _transfer_guidance(config: HornOptimizerConfig) -> dict[str, Any]:
    if not TRANSFER_RESULTS.is_file():
        return {
            "status": "pending",
            "common_length_rule": "width-height-weighted",
            "wider_first_round": False,
            "support_warnings": [
                "non-round transfer result is not available; using the "
                "preregistered weighted fallback",
            ],
        }
    result = _read_json(TRANSFER_RESULTS)
    selected = set(result.get("promotion", {}).get(
        "wider_first_round_intents", []))
    width, height = config.mouth.dimensions()
    regions = []
    for row in result.get("locked_evidence", []):
        if row.get("source_intent_id") not in selected:
            continue
        region = {
            "intent_id": row["source_intent_id"],
            "mouth_width_mm": float(row["mouth_width_mm"]),
            "mouth_height_mm": float(row["mouth_height_mm"]),
            "horizontal_coverage_deg": float(
                row["horizontal_coverage_deg"]),
            "vertical_coverage_deg": float(row["vertical_coverage_deg"]),
        }
        if region not in regions:
            regions.append(region)
    wider = any(
        abs(width-row["mouth_width_mm"]) <= 50
        and abs(height-row["mouth_height_mm"]) <= 50
        and abs(config.horizontal_coverage_deg
                - row["horizontal_coverage_deg"]) <= 5
        and abs(config.vertical_coverage_deg
                - row["vertical_coverage_deg"]) <= 5
        for row in regions
    )
    warnings = []
    if config.mouth_shape == "square":
        corner = result.get("equal_hv_square_summary", {})
        warnings.append(
            "square-corner transfer is measured support evidence, not a "
            f"global correction (median equal-H/V delta "
            f"{float(corner.get('median_surface_delta_from_round_points', 0)):.3f} "
            "surface points)")
    if wider:
        warnings.append(
            "intent lies near a locked transfer failure; first-round H/V and "
            "length exploration is widened")
    return {
        "status": "measured",
        "results_sha256": _hash({
            key: value for key, value in result.items()
            if key != "content_sha256"
        }),
        "reported_content_sha256": result.get("content_sha256"),
        "common_length_rule": _transfer_length_rule(),
        "wider_first_round": wider,
        "wider_regions": regions,
        "support_warnings": warnings,
    }


class HornOptimizer:
    """Own one optimizer run directory and its restartable state."""

    def __init__(
        self,
        config: HornOptimizerConfig,
        *,
        response_library: Iterable[dict[str, Any]] | None = None,
        queue_runner: Callable[..., dict[str, Any]] = run_queue,
    ):
        self.config = config
        self.output = config.output_dir
        self.state_path = self.output / STATE_NAME
        self.queue_runner = queue_runner
        self._report_lock = threading.Lock()
        self._provided_library = (
            list(response_library) if response_library is not None else None)
        self.rules = RoundControlHeuristics.load(HEURISTICS)

    def _config_snapshot(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "schema_version": 1,
            "source_path": str(cfg.source_path),
            "output_dir": str(cfg.output_dir),
            "intent": {
                "horizontal_coverage_deg": cfg.horizontal_coverage_deg,
                "vertical_coverage_deg": cfg.vertical_coverage_deg,
            },
            "throat_angle_deg": cfg.throat_angle_deg,
            "mouth_shape": cfg.mouth_shape,
            "mouth": {
                "width_mm": cfg.mouth.width_mm.as_list(),
                "height_mm": (
                    cfg.mouth.height_mm.as_list()
                    if cfg.mouth.height_mm else None),
                "aspect_ratio": (
                    cfg.mouth.aspect_ratio.as_list()
                    if cfg.mouth.aspect_ratio else None),
            },
            "sag_axes": cfg.sag_axes,
            "sag_mm": cfg.sag_mm.as_list(),
            "max_simulations": cfg.max_simulations,
            "approval_mode": cfg.approval_mode,
            "seed_yaml": str(cfg.seed_yaml) if cfg.seed_yaml else None,
            "practical_limits": {
                "length_mm": (
                    cfg.practical_limits.length_mm.as_list()
                    if cfg.practical_limits.length_mm else None),
                "extension_mm":
                    cfg.practical_limits.extension_mm.as_list(),
                "k_horizontal":
                    cfg.practical_limits.k_horizontal.as_list(),
                "k_vertical": cfg.practical_limits.k_vertical.as_list(),
                "n_horizontal":
                    cfg.practical_limits.n_horizontal.as_list(),
                "n_vertical": cfg.practical_limits.n_vertical.as_list(),
            },
            "ranking": {
                "enabled": cfg.ranking.enabled,
                "surface_shortlist_points":
                    cfg.ranking.surface_shortlist_points,
                "tie_break": cfg.ranking.tie_break,
            },
            "solver": {
                "lower_frequency_hz": cfg.solver.lower_frequency_hz,
                "crossover_hz": cfg.solver.crossover_hz,
                "upper_frequency_hz": cfg.solver.upper_frequency_hz,
                "points_per_octave": cfg.solver.points_per_octave,
                "confirmation_points_per_octave":
                    cfg.solver.confirmation_points_per_octave,
                "elements_per_wavelength":
                    cfg.solver.elements_per_wavelength,
                "angles": cfg.solver.angles,
                "workers": cfg.solver.workers,
            },
        }

    def initialize(self) -> dict[str, Any]:
        if self.state_path.is_file():
            return self.load_state()
        self.output.mkdir(parents=True, exist_ok=True)
        snapshot = self._config_snapshot()
        transfer = _transfer_guidance(self.config)
        state = {
            "schema_version": 1,
            "optimizer": "horn_optimizer",
            "optimizer_version": 1,
            "status": "initialized",
            "created_at_unix": time.time(),
            "updated_at_unix": time.time(),
            "config": snapshot,
            "config_hash": _hash(snapshot),
            "transfer_length_rule": transfer["common_length_rule"],
            "transfer_guidance": transfer,
            "support_warnings": transfer["support_warnings"],
            "rounds": [],
            "candidates": [],
            "branch_backlog": [],
            "response_approximation": {
                "scope": "finite run-specific proposal pools only",
                "method": "inverse-distance weighting of measured candidates",
                "portable_prediction": False,
            },
            "next_round": 0,
            "non_improving_rounds": 0,
            "step_sizes": {
                "length_fraction": 0.12,
                "extension_mm": 20.0,
                "k": 0.75,
                "n": 4.0,
                "mouth_mm": 20.0,
                "aspect_ratio": 0.1,
                "sag_mm": 10.0,
            },
            "accounting": {
                "max_simulations": self.config.max_simulations,
                "solver_evaluations": 0,
                "exact_library_reuses": 0,
                "geometry_rejections": 0,
                "interrupted_retries": 0,
                "solver_recovery_retries": 0,
                "failed_evaluations": 0,
                "confirmation_evaluations": 0,
            },
            "early_stopping": {
                "contracted_local_search": False,
                "two_non_improving_rounds": False,
                "no_feasible_heuristic_branch": False,
                "reason": None,
            },
            "winner_proposal_hash": None,
        }
        self.save_state(state)
        self.render_report(state)
        return state

    def load_state(self) -> dict[str, Any]:
        state = _read_json(self.state_path)
        if (
            state.get("optimizer") != "horn_optimizer"
            or state.get("optimizer_version") != 1
            or state.get("schema_version") != 1
        ):
            raise ValueError("unsupported horn optimizer restart state")
        snapshot = self._config_snapshot()
        if state.get("config_hash") != _hash(snapshot):
            raise ValueError(
                "optimizer YAML changed after initialization; use a new "
                "output_dir or restore the original contract")
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        state["updated_at_unix"] = time.time()
        _write_json(self.state_path, state)

    def _seed_document(self) -> dict[str, Any]:
        document = _load_yaml(self.config.seed_yaml or BASE_PROJECT)
        if self.config.seed_yaml:
            self._validate_seed(document)
        return document

    def _validate_seed(self, document: dict[str, Any]) -> None:
        config = document["horncad_config"]
        global_config = config["global"]
        intent = config.get("operating_intent", {})
        width = float(global_config["mouth_width"])
        height = float(global_config["mouth_height"])
        if not _range_contains(self.config.mouth.width_mm, width):
            raise ValueError("seed mouth width is outside the configured range")
        if self.config.mouth.height_mm:
            if not _range_contains(self.config.mouth.height_mm, height):
                raise ValueError(
                    "seed mouth height is outside the configured range")
        else:
            assert self.config.mouth.aspect_ratio
            if not _range_contains(
                    self.config.mouth.aspect_ratio, width/height):
                raise ValueError(
                    "seed mouth aspect ratio is outside the configured range")
        fixed = (
            ("horizontal coverage", intent.get("horizontal_coverage_deg"),
             self.config.horizontal_coverage_deg),
            ("vertical coverage", intent.get("vertical_coverage_deg"),
             self.config.vertical_coverage_deg),
            ("throat angle", global_config.get("throat_angle_deg"),
             self.config.throat_angle_deg),
            ("mouth squareness",
             config.get("section_modifier", {}).get("mouth_squareness", 0),
             _shape_squareness(self.config.mouth_shape)),
        )
        for label, actual, expected in fixed:
            if not math.isclose(
                    float(actual), float(expected), abs_tol=1e-8):
                raise ValueError(
                    f"seed {label} is incompatible with fixed intent")
        h_sag, v_sag = _sag_flags(self.config.sag_axes)
        if bool(global_config.get("mouth_sag_h_enabled", False)) != h_sag:
            raise ValueError("seed horizontal sag axis is incompatible")
        if bool(global_config.get("mouth_sag_v_enabled", False)) != v_sag:
            raise ValueError("seed vertical sag axis is incompatible")
        sag = float(global_config.get("mouth_sag", 0))
        if not _range_contains(self.config.sag_mm, sag):
            raise ValueError("seed sag amount is outside the configured range")

    def _heuristic_values(
        self, width: float | None = None, secondary: float | None = None,
        *, length_rule: str | None = None,
    ) -> dict[str, float]:
        width, height = self.config.mouth.dimensions(width, secondary)
        intent = DesignIntent(
            width, height, self.config.horizontal_coverage_deg,
            self.config.vertical_coverage_deg)
        seed = self.rules.recommend(intent)
        rule = length_rule or _transfer_length_rule()
        if rule == "s-balanced":
            # Use the preregistered transfer-study S-balanced construction:
            # the mouth-weighted sum of log S departures is zero.
            low = min(
                seed.horizontal.profile_length_mm,
                seed.vertical.profile_length_mm)
            high = max(
                seed.horizontal.profile_length_mm,
                seed.vertical.profile_length_mm)
            h_target = self.rules._s_at_length(
                width, self.config.horizontal_coverage_deg,
                seed.horizontal.profile_length_mm,
                seed.k_horizontal, seed.n_horizontal)
            v_target = self.rules._s_at_length(
                height, self.config.vertical_coverage_deg,
                seed.vertical.profile_length_mm,
                seed.k_vertical, seed.n_vertical)
            if min(h_target, v_target) <= 0:
                raise ValueError(
                    "independent H/V heuristic seed has nonpositive S")

            def balance(length: float) -> float:
                s_h = self.rules._s_at_length(
                    width, self.config.horizontal_coverage_deg, length,
                    seed.k_horizontal, seed.n_horizontal)
                s_v = self.rules._s_at_length(
                    height, self.config.vertical_coverage_deg, length,
                    seed.k_vertical, seed.n_vertical)
                if min(s_h, s_v) <= 0:
                    return -math.inf
                return (
                    width*math.log(s_h/h_target)
                    + height*math.log(s_v/v_target)
                )

            low_value = balance(low)
            high_value = balance(high)
            if low_value*high_value > 0:
                raise ValueError(
                    "independent H/V lengths do not bracket S balance")
            for _ in range(80):
                middle = (low+high)/2
                value = balance(middle)
                if low_value*value <= 0:
                    high, high_value = middle, value
                else:
                    low, low_value = middle, value
            length = (low+high)/2
        else:
            length = seed.flat_profile_length_mm
        if self.config.practical_limits.length_mm:
            length = self.config.practical_limits.length_mm.clamp(length)
        return {
            "mouth_width_mm": width,
            "mouth_height_mm": height,
            "length_mm": length,
            "extension_mm": self.config.practical_limits.extension_mm.clamp(
                seed.extension_mm),
            "k_h": self.config.practical_limits.k_horizontal.clamp(
                seed.k_horizontal),
            "k_v": self.config.practical_limits.k_vertical.clamp(
                seed.k_vertical),
            "n_h": self.config.practical_limits.n_horizontal.clamp(
                seed.n_horizontal),
            "n_v": self.config.practical_limits.n_vertical.clamp(
                seed.n_vertical),
            "sag_mm": self.config.sag_mm.midpoint,
        }

    def _baseline_values(self) -> dict[str, float]:
        if self.config.seed_yaml:
            return {
                key: _normalized_number(value)
                for key, value in _project_values(
                    self._seed_document()).items()
            }
        return self._heuristic_values()

    def _clamp_values(self, values: dict[str, float]) -> dict[str, float]:
        result = {key: float(value) for key, value in values.items()}
        result["mouth_width_mm"] = self.config.mouth.width_mm.clamp(
            result["mouth_width_mm"])
        if self.config.mouth.height_mm:
            result["mouth_height_mm"] = self.config.mouth.height_mm.clamp(
                result["mouth_height_mm"])
        else:
            assert self.config.mouth.aspect_ratio
            aspect = self.config.mouth.aspect_ratio.clamp(
                result["mouth_width_mm"]/result["mouth_height_mm"])
            result["mouth_height_mm"] = result["mouth_width_mm"]/aspect
        limits = self.config.practical_limits
        if limits.length_mm:
            result["length_mm"] = limits.length_mm.clamp(result["length_mm"])
        result["extension_mm"] = limits.extension_mm.clamp(
            result["extension_mm"])
        result["k_h"] = limits.k_horizontal.clamp(result["k_h"])
        result["k_v"] = limits.k_vertical.clamp(result["k_v"])
        result["n_h"] = limits.n_horizontal.clamp(result["n_h"])
        result["n_v"] = limits.n_vertical.clamp(result["n_v"])
        result["sag_mm"] = self.config.sag_mm.clamp(result["sag_mm"])
        return {key: _normalized_number(result[key]) for key in COORDINATE_FIELDS}

    def _s_guided_control_move(
        self, values: dict[str, float], key: str, target: float,
    ) -> dict[str, float]:
        """Change one K/N control and rebuild common length from H/V S seeds."""
        bounds = getattr(
            self.config.practical_limits,
            {
                "k_h": "k_horizontal",
                "n_h": "n_horizontal",
                "k_v": "k_vertical",
                "n_v": "n_vertical",
            }[key],
        )
        target = bounds.clamp(target)
        moved = {**values, key: target}
        width = moved["mouth_width_mm"]
        height = moved["mouth_height_mm"]
        h_seed = self.rules.axis_length(
            width, self.config.horizontal_coverage_deg)
        v_seed = self.rules.axis_length(
            height, self.config.vertical_coverage_deg)
        h_axis = self.rules.length_for_target_s(
            width, self.config.horizontal_coverage_deg,
            moved["k_h"], moved["n_h"], h_seed.target_s)
        v_axis = self.rules.length_for_target_s(
            height, self.config.vertical_coverage_deg,
            moved["k_v"], moved["n_v"], v_seed.target_s)
        rule = _transfer_length_rule()
        if rule == "s-balanced":
            low = min(h_axis.profile_length_mm, v_axis.profile_length_mm)
            high = max(h_axis.profile_length_mm, v_axis.profile_length_mm)

            def residual(length: float) -> float:
                h_s = self.rules._s_at_length(
                    width, self.config.horizontal_coverage_deg, length,
                    moved["k_h"], moved["n_h"])
                v_s = self.rules._s_at_length(
                    height, self.config.vertical_coverage_deg, length,
                    moved["k_v"], moved["n_v"])
                if min(h_s, v_s) <= 0:
                    return -math.inf
                return (
                    width*math.log(h_s/h_seed.target_s)
                    + height*math.log(v_s/v_seed.target_s)
                )

            low_value = residual(low)
            high_value = residual(high)
            if low_value*high_value > 0:
                raise ValueError("S-guided axis lengths do not bracket balance")
            for _ in range(80):
                middle = (low+high)/2
                value = residual(middle)
                if low_value*value <= 0:
                    high, high_value = middle, value
                else:
                    low, low_value = middle, value
            common = (low+high)/2
        else:
            common = (
                width*h_axis.profile_length_mm
                + height*v_axis.profile_length_mm
            ) / (width+height)
        if self.config.practical_limits.length_mm:
            common = self.config.practical_limits.length_mm.clamp(common)
        moved["length_mm"] = common
        return moved

    def _candidate(
        self, values: dict[str, float], round_number: int, branch: str,
        *, parent_hash: str | None = None, force_new: bool = False,
        preserve_values: bool = False,
    ) -> dict[str, Any]:
        values = (
            {
                key: _normalized_number(values[key])
                for key in COORDINATE_FIELDS
            }
            if preserve_values else self._clamp_values(values)
        )
        coordinate = coordinate_hash(self.config, values)
        proposal = proposal_hash(
            coordinate, round_number, branch, parent_hash)
        return {
            "id": f"r{round_number:02d}-{branch}-{proposal[:10]}",
            "round": round_number,
            "branch": branch,
            "parent_hash": parent_hash,
            "coordinate_hash": coordinate,
            "proposal_hash": proposal,
            "values": values,
            "status": (
                "awaiting_approval"
                if self.config.approval_mode == "approval-gated"
                else "proposed"
            ),
            "force_new_evaluation": force_new,
            "lineage": [item for item in (parent_hash, proposal) if item],
        }

    def _round_one_pool(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        base = self._baseline_values()
        wider = state["transfer_guidance"].get(
            "wider_first_round", False)
        k_step = 1.25 if wider else 0.75
        n_step = 6 if wider else 4
        candidates = []
        for rule in ("width-height-weighted", "s-balanced"):
            candidates.append(
                (self._heuristic_values(length_rule=rule), f"length-{rule}"))
        for key, delta, branch in (
            ("k_h", k_step, "h-axis-k"),
            ("n_h", n_step, "h-axis-n"),
            ("k_v", k_step, "v-axis-k"),
            ("n_v", n_step, "v-axis-n"),
        ):
            for sign, suffix in ((-1, "low"), (1, "high")):
                target = getattr(
                    self.config.practical_limits,
                    {
                        "k_h": "k_horizontal",
                        "n_h": "n_horizontal",
                        "k_v": "k_vertical",
                        "n_v": "n_vertical",
                    }[key],
                ).clamp(base[key]+sign*delta)
                try:
                    moved = self._s_guided_control_move(base, key, target)
                except ValueError:
                    continue
                candidates.append((moved, f"{branch}-{suffix}"))
        candidates.append((
            {
                **base,
                "extension_mm":
                    self.config.practical_limits.extension_mm.maximum,
            },
            "extension-high",
        ))
        mouth = self.config.mouth
        if not mouth.width_mm.scalar:
            for value, label in (
                (mouth.width_mm.minimum, "mouth-width-low"),
                (mouth.width_mm.maximum, "mouth-width-high"),
            ):
                candidates.append(
                    (self._heuristic_values(width=value), label))
        secondary_bounds = mouth.height_mm or mouth.aspect_ratio
        assert secondary_bounds
        if not secondary_bounds.scalar:
            for value, label in (
                (secondary_bounds.minimum, "mouth-secondary-low"),
                (secondary_bounds.maximum, "mouth-secondary-high"),
            ):
                candidates.append(
                    (self._heuristic_values(secondary=value), label))
        if self.config.sag_axes != "none" and not self.config.sag_mm.scalar:
            candidates.extend([
                ({**base, "sag_mm": self.config.sag_mm.minimum}, "sag-low"),
                ({**base, "sag_mm": self.config.sag_mm.maximum}, "sag-high"),
            ])
        baseline = next((
            row for row in state["candidates"]
            if row["branch"] in {"seed-baseline", "heuristic-baseline"}
        ), None)
        parent_hash = baseline["proposal_hash"] if baseline else None
        pool = [
            self._candidate(
                values, 1, branch, parent_hash=parent_hash)
            for values, branch in candidates
        ]
        if baseline:
            for candidate in pool:
                candidate["lineage"] = (
                    list(baseline.get("lineage", []))
                    + [candidate["proposal_hash"]]
                )
        return self._deduplicate_candidates(state, pool)

    def _local_pool(self, state: dict[str, Any],
                    round_number: int) -> list[dict[str, Any]]:
        ranking = self.ranking(state)
        anchors = ranking[:3]
        steps = state["step_sizes"]
        pool: list[tuple[dict[str, float], str, str | None]] = []
        for anchor_index, anchor in enumerate(anchors):
            values = anchor["values"]
            parent = anchor["proposal_hash"]
            moves = (
                ("k_h", steps["k"], "h-axis-k"),
                ("n_h", steps["n"], "h-axis-n"),
                ("k_v", steps["k"], "v-axis-k"),
                ("n_v", steps["n"], "v-axis-n"),
                ("extension_mm", steps["extension_mm"], "extension"),
                ("mouth_width_mm", steps["mouth_mm"], "mouth-width"),
                ("sag_mm", steps["sag_mm"], "sag"),
            )
            for key, delta, label in moves:
                if key == "sag_mm" and self.config.sag_axes == "none":
                    continue
                for sign, suffix in ((-1, "low"), (1, "high")):
                    moved = {**values, key: values[key]+sign*delta}
                    if key in {"k_h", "n_h", "k_v", "n_v"}:
                        try:
                            moved = self._s_guided_control_move(
                                values, key, moved[key])
                        except ValueError:
                            continue
                    pool.append(
                        (moved, f"{label}-{suffix}-b{anchor_index}", parent))
            for sign, suffix in ((-1, "short"), (1, "long")):
                pool.append((
                    {**values, "length_mm": values["length_mm"]*(
                        1+sign*steps["length_fraction"])},
                    f"length-{suffix}-b{anchor_index}", parent,
                ))
            mouth = self.config.mouth
            if mouth.height_mm and not mouth.height_mm.scalar:
                for sign, suffix in ((-1, "low"), (1, "high")):
                    pool.append((
                        {
                            **values,
                            "mouth_height_mm":
                                values["mouth_height_mm"]
                                + sign*steps["mouth_mm"],
                        },
                        f"mouth-height-{suffix}-b{anchor_index}",
                        parent,
                    ))
            if mouth.aspect_ratio and not mouth.aspect_ratio.scalar:
                aspect = (
                    values["mouth_width_mm"]
                    / values["mouth_height_mm"])
                for sign, suffix in ((-1, "low"), (1, "high")):
                    moved_aspect = mouth.aspect_ratio.clamp(
                        aspect+sign*steps["aspect_ratio"])
                    pool.append((
                        {
                            **values,
                            "mouth_height_mm":
                                values["mouth_width_mm"]/moved_aspect,
                        },
                        f"mouth-aspect-{suffix}-b{anchor_index}",
                        parent,
                    ))
        candidates = [
            self._candidate(
                values, round_number, branch, parent_hash=parent)
            for values, branch, parent in pool
        ]
        by_hash = {
            row["proposal_hash"]: row for row in state["candidates"]
        }
        for candidate in candidates:
            parent = by_hash.get(candidate.get("parent_hash"))
            if parent:
                candidate["lineage"] = (
                    list(parent.get("lineage", []))
                    + [candidate["proposal_hash"]]
                )
        return self._deduplicate_candidates(state, candidates)

    @staticmethod
    def _deduplicate_candidates(
        state: dict[str, Any], candidates: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing = {
            row["coordinate_hash"] for row in state["candidates"]
            if not row.get("force_new_evaluation")
        }
        output = []
        for candidate in candidates:
            coordinate = candidate["coordinate_hash"]
            if coordinate in existing:
                continue
            existing.add(coordinate)
            output.append(candidate)
        return output

    def _prioritize_pool(
        self, state: dict[str, Any], pool: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Order only this finite pool from nearby measurements.

        This approximation is deliberately run-local and is discarded after
        proposal selection; it is not a released response predictor.
        """
        measured = self.ranking(state)
        if not measured:
            return sorted(
                pool, key=lambda row: (row["branch"], row["coordinate_hash"]))
        steps = state["step_sizes"]
        scales = {
            "mouth_width_mm": max(steps["mouth_mm"], 1),
            "mouth_height_mm": max(steps["mouth_mm"], 1),
            "length_mm": max(
                measured[0]["values"]["length_mm"]
                * steps["length_fraction"], 1),
            "extension_mm": max(steps["extension_mm"], 1),
            "k_h": max(steps["k"], 0.1),
            "k_v": max(steps["k"], 0.1),
            "n_h": max(steps["n"], 0.5),
            "n_v": max(steps["n"], 0.5),
            "sag_mm": max(steps["sag_mm"], 1),
        }
        for candidate in pool:
            neighbors = []
            for evidence in measured:
                distance = math.sqrt(sum(
                    ((candidate["values"][key]-evidence["values"][key])
                     / scales[key])**2
                    for key in COORDINATE_FIELDS
                ))
                neighbors.append((distance, evidence))
            neighbors.sort(key=lambda item: (
                item[0], item[1]["coordinate_hash"]))
            nearest = neighbors[:min(4, len(neighbors))]
            weights = [1/(distance+0.25) for distance, _row in nearest]
            candidate["local_pool_priority"] = sum(
                weight*float(row["surface_score_v2_3"])
                for weight, (_distance, row) in zip(weights, nearest)
            ) / sum(weights)
            candidate["nearest_evidence_hashes"] = [
                row["coordinate_hash"] for _distance, row in nearest
            ]
        # Keep the first choice from each physical move group competitive so a
        # single local basin cannot erase every alternative branch.
        family_order = {
            "h": 0, "v": 1, "length": 2, "extension": 3,
            "mouth": 4, "sag": 5,
        }

        def family(row: dict[str, Any]) -> int:
            return next((
                order for prefix, order in family_order.items()
                if row["branch"].startswith(prefix)
            ), 6)

        return sorted(
            pool,
            key=lambda row: (
                -float(row.get("local_pool_priority", -math.inf)),
                family(row),
                row["coordinate_hash"],
            ),
        )

    def propose(self) -> list[dict[str, Any]]:
        state = self.initialize()
        if state["status"] in {"complete", "budget-exhausted"}:
            return []
        if any(row["status"] in {
                "proposed", "awaiting_approval", "running", "interrupted",
                "dry-run",
            } for row in state["candidates"]):
            return [
                row for row in state["candidates"]
                if row["status"] in {
                    "proposed", "awaiting_approval", "running", "interrupted",
                    "dry-run",
                }
            ]
        round_number = int(state["next_round"])
        if round_number == 0:
            pool = [self._candidate(
                self._baseline_values(), 0, "seed-baseline"
                if self.config.seed_yaml else "heuristic-baseline",
                preserve_values=bool(self.config.seed_yaml))]
        elif state["branch_backlog"]:
            pool = []
            for row in state["branch_backlog"]:
                candidate = self._candidate(
                    row["values"], round_number, row["branch"],
                    parent_hash=row.get("parent_hash"),
                    force_new=row.get("force_new_evaluation", False),
                )
                candidate["lineage"] = (
                    list(row.get("lineage", []))[:-1]
                    + [candidate["proposal_hash"]]
                )
                pool.append(candidate)
            state["branch_backlog"] = []
        elif round_number == 1:
            pool = self._round_one_pool(state)
        else:
            pool = self._local_pool(state, round_number)
        pool = self._prioritize_pool(state, pool)
        selected = pool[:4]
        state["branch_backlog"] = pool[4:]
        state["candidates"].extend(selected)
        state["rounds"].append({
            "round": round_number,
            "proposal_hashes": [row["proposal_hash"] for row in selected],
            "status": (
                "awaiting-approval"
                if self.config.approval_mode == "approval-gated"
                else "proposed"),
            "best_before": (
                self.ranking(state)[0]["proposal_hash"]
                if self.ranking(state) else None),
        })
        state["next_round"] = round_number+1
        if not selected:
            state["early_stopping"]["no_feasible_heuristic_branch"] = True
            self._close_round(state)
        self.save_state(state)
        self.render_report(state)
        return selected

    def approve(self) -> int:
        state = self.load_state()
        count = 0
        for row in state["candidates"]:
            if row["status"] == "awaiting_approval":
                row["status"] = "proposed"
                count += 1
        for round_row in state["rounds"]:
            if round_row["status"] == "awaiting-approval":
                round_row["status"] = "proposed"
        self.save_state(state)
        self.render_report(state)
        return count

    def _candidate_dir(self, candidate: dict[str, Any]) -> Path:
        return self.output / "candidates" / candidate["id"]

    def _search_document(
        self, candidate: dict[str, Any], project_path: Path,
        *, confirmation: bool = False,
    ) -> dict[str, Any]:
        values = candidate["values"]
        epsilon = 1e-6
        bounds = {
            "length_mm": [
                values["length_mm"]-epsilon, values["length_mm"]+epsilon],
            "extension_mm": [
                values["extension_mm"]-epsilon,
                values["extension_mm"]+epsilon],
            "osse_coverage_h_deg": [
                self.config.horizontal_coverage_deg-epsilon,
                self.config.horizontal_coverage_deg+epsilon],
            "osse_coverage_v_deg": [
                self.config.vertical_coverage_deg-epsilon,
                self.config.vertical_coverage_deg+epsilon],
            "k_h": [values["k_h"]-epsilon, values["k_h"]+epsilon],
            "k_v": [values["k_v"]-epsilon, values["k_v"]+epsilon],
            "n_h": [values["n_h"]-epsilon, values["n_h"]+epsilon],
            "n_v": [values["n_v"]-epsilon, values["n_v"]+epsilon],
        }
        solver = self.config.solver
        return {"bem_candidate_search": {
            "version": 1,
            "seed_yaml": project_path.name,
            "intended_coverage_h_deg": self.config.horizontal_coverage_deg,
            "intended_coverage_v_deg": self.config.vertical_coverage_deg,
            "lower_frequency_hz": solver.lower_frequency_hz,
            "crossover_hz": solver.crossover_hz,
            "upper_frequency_hz": solver.upper_frequency_hz,
            "max_evaluations": 1,
            "initial_candidates": 0,
            "minimum_candidate_distance": 0.001,
            "derived_s_bounds": [0.0, 4.0],
            "sampling_stability_points": 2.0,
            "confirmation_points_per_octave":
                solver.confirmation_points_per_octave,
            "adaptive_pruning": {"enabled": False},
            "fixed_design": True,
            "bounds": bounds,
            "solver": {
                "points_per_octave": (
                    solver.confirmation_points_per_octave
                    if confirmation else solver.points_per_octave),
                "elements_per_wavelength": solver.elements_per_wavelength,
                "angles": solver.angles,
                "workers": solver.workers,
            },
            "horn_optimizer": {
                "version": 1,
                "proposal_hash": candidate["proposal_hash"],
                "coordinate_hash": candidate["coordinate_hash"],
                "branch": candidate["branch"],
                "confirmation": confirmation,
            },
        }}

    def materialize(self, candidate: dict[str, Any]) -> tuple[Path, Path, dict]:
        directory = self._candidate_dir(candidate)
        project_path = directory / "project.yaml"
        search_path = directory / "search.yaml"
        if project_path.is_file() and search_path.is_file():
            project = _load_yaml(project_path)
            search = yaml.safe_load(
                search_path.read_text(encoding="utf-8"))
            return project_path, search_path, project
        base = self._seed_document()
        global_config = base["horncad_config"]["global"]
        global_config["mouth_width"] = candidate["values"]["mouth_width_mm"]
        global_config["mouth_height"] = candidate["values"]["mouth_height_mm"]
        global_config["throat_angle_deg"] = self.config.throat_angle_deg
        global_config["mouth_sag"] = candidate["values"]["sag_mm"]
        h_sag, v_sag = _sag_flags(self.config.sag_axes)
        global_config["mouth_sag_h_enabled"] = h_sag
        global_config["mouth_sag_v_enabled"] = v_sag
        base["horncad_config"]["section_modifier"]["mouth_squareness"] = (
            _shape_squareness(self.config.mouth_shape))
        search_values = {
            "length_mm": candidate["values"]["length_mm"],
            "extension_mm": candidate["values"]["extension_mm"],
            "osse_coverage_h_deg": self.config.horizontal_coverage_deg,
            "osse_coverage_v_deg": self.config.vertical_coverage_deg,
            "k_h": candidate["values"]["k_h"],
            "k_v": candidate["values"]["k_v"],
            "n_h": candidate["values"]["n_h"],
            "n_v": candidate["values"]["n_v"],
        }
        materialize_search = {
            "intended_coverage_h_deg": self.config.horizontal_coverage_deg,
            "intended_coverage_v_deg": self.config.vertical_coverage_deg,
            "lower_frequency_hz": self.config.solver.lower_frequency_hz,
            "crossover_hz": self.config.solver.crossover_hz,
            "upper_frequency_hz": self.config.solver.upper_frequency_hz,
        }
        project, derived = materialize_candidate(
            base, search_values, materialize_search)
        feasible, reason = geometry_feasibility(derived)
        candidate["derived"] = derived
        if not feasible:
            candidate["status"] = "geometry-rejected"
            candidate["reason"] = reason
            return project_path, search_path, project
        search = self._search_document(
            candidate, project_path,
            confirmation=candidate["branch"] == "final-confirmation")
        _write_yaml(project_path, project)
        _write_yaml(search_path, search)
        return project_path, search_path, project

    def _library(
        self, target_hashes: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self._provided_library is not None:
            return self._provided_library
        rows = []
        # Local runtime states are the fast path. They are intentionally
        # untracked, so the compact-artifact scan below remains the fresh-clone
        # fallback.
        for state_path in sorted(ROOT.glob("examples/**/search_state.json")):
            try:
                state = _read_json(state_path)
                search_document = yaml.safe_load(
                    (state_path.parent / "search.yaml").read_text(
                        encoding="utf-8"))
                if not self._compatible_search(search_document):
                    continue
                for record in state.get("candidates", []):
                    if record.get("status") != "complete":
                        continue
                    project_path = (
                        state_path.parent / "candidates"
                        / str(record["id"]) / "project.yaml")
                    project = _load_yaml(project_path)
                    if not self._compatible_project(project):
                        continue
                    coordinate = coordinate_hash(
                        self.config, _project_values(project))
                    if (
                        target_hashes is not None
                        and coordinate not in target_hashes
                    ):
                        continue
                    measurement = self._measurement_from_record(record)
                    rows.append({
                        "coordinate_hash": coordinate,
                        **measurement,
                        "response_path": str(
                            project_path.parent / "bem" / "responses.npz"),
                        "project_path": str(project_path),
                    })
            except (
                KeyError, TypeError, ValueError, OSError,
                json.JSONDecodeError, IndexError,
            ):
                continue
        found = {row["coordinate_hash"] for row in rows}
        missing = (
            target_hashes-found if target_hashes is not None else None)
        if target_hashes is not None and not missing:
            return rows
        projects = sorted(
            ROOT.glob("examples/**/candidates/candidate-*/project.yaml"))
        for project_path in projects:
            candidate_dir = project_path.parent
            response_path = candidate_dir / "bem" / "responses.npz"
            search_path = project_path.parents[2] / "search.yaml"
            surface_path = candidate_dir / "bem" / "surface_diagnostics.json"
            impedance_path = (
                candidate_dir / "bem" / "throat_impedance_diagnostics.json")
            if not all(path.is_file() for path in (
                    response_path, search_path, surface_path, impedance_path)):
                continue
            try:
                project = _load_yaml(project_path)
                if not self._compatible_project(project):
                    continue
                search_document = yaml.safe_load(
                    search_path.read_text(encoding="utf-8"))
                if not self._compatible_search(search_document):
                    continue
                values = _project_values(project)
                coordinate = coordinate_hash(self.config, values)
                if missing is not None and coordinate not in missing:
                    continue
                surface_document = _read_json(surface_path)
                impedance_document = _read_json(impedance_path)
                surface = next(
                    value["score"]
                    for value in surface_document.values()
                    if isinstance(value, dict)
                    and isinstance(value.get("score"), dict)
                    and value["score"].get("version") == "v2.3"
                )
                impedance = next(
                    value
                    for value in impedance_document.values()
                    if isinstance(value, dict)
                    and value.get("diagnostic_version") == "2.3.0"
                )
                rows.append({
                    "coordinate_hash": coordinate,
                    "surface_score_v2_3":
                        float(surface["overall_percent"]),
                    "throat_impedance_score_v2_3_0":
                        float(impedance["overall_percent"]),
                    "response_path": str(response_path),
                    "project_path": str(project_path),
                })
            except (
                KeyError, StopIteration, TypeError, ValueError, OSError,
                json.JSONDecodeError, IndexError,
            ):
                continue
        return rows

    def _compatible_search(self, document: Any) -> bool:
        if not isinstance(document, dict):
            return False
        search = document.get("bem_candidate_search")
        if not isinstance(search, dict):
            return False
        solver = search.get("solver", {})
        required = self.config.solver
        comparisons = (
            (search.get("lower_frequency_hz"), required.lower_frequency_hz),
            (search.get("crossover_hz"), required.crossover_hz),
            (search.get("upper_frequency_hz"), required.upper_frequency_hz),
            (solver.get("points_per_octave"), required.points_per_octave),
            (solver.get("elements_per_wavelength"),
             required.elements_per_wavelength),
            (solver.get("angles"), required.angles),
        )
        try:
            return all(math.isclose(
                float(actual), float(expected), abs_tol=1e-9)
                for actual, expected in comparisons)
        except (TypeError, ValueError):
            return False

    def _compatible_project(self, project: dict[str, Any]) -> bool:
        config = project["horncad_config"]
        global_config = config["global"]
        intent = config.get("operating_intent", {})
        h_sag, v_sag = _sag_flags(self.config.sag_axes)
        return all((
            math.isclose(
                float(intent.get("horizontal_coverage_deg", math.nan)),
                self.config.horizontal_coverage_deg, abs_tol=1e-8),
            math.isclose(
                float(intent.get("vertical_coverage_deg", math.nan)),
                self.config.vertical_coverage_deg, abs_tol=1e-8),
            math.isclose(
                float(global_config.get("throat_angle_deg", math.nan)),
                self.config.throat_angle_deg, abs_tol=1e-8),
            math.isclose(
                float(config.get("section_modifier", {}).get(
                    "mouth_squareness", 0)),
                _shape_squareness(self.config.mouth_shape), abs_tol=1e-8),
            bool(global_config.get("mouth_sag_h_enabled", False)) == h_sag,
            bool(global_config.get("mouth_sag_v_enabled", False)) == v_sag,
        ))

    @staticmethod
    def _measurement_from_record(record: dict[str, Any]) -> dict[str, Any]:
        surface = record["surface_diagnostics"]["score"]
        impedance = record["throat_impedance_diagnostics"]
        if (
            surface.get("version") != "v2.3"
            or impedance.get("diagnostic_version") != "2.3.0"
        ):
            raise ValueError("solver result does not use required diagnostics")
        return {
            "surface_score_v2_3": float(surface["overall_percent"]),
            "throat_impedance_score_v2_3_0":
                float(impedance["overall_percent"]),
        }

    def _harvest(self, state: dict[str, Any],
                 candidate: dict[str, Any]) -> bool:
        search_state_path = self._candidate_dir(candidate) / "search_state.json"
        if not search_state_path.is_file():
            return False
        search_state = _read_json(search_state_path)
        record = (search_state.get("candidates") or [{}])[0]
        if record.get("status") == "complete":
            candidate.update(self._measurement_from_record(record))
            candidate["status"] = "complete"
            candidate["response_path"] = str(
                self._candidate_dir(candidate)
                / "candidates" / record["id"] / "bem" / "responses.npz")
            candidate["report_path"] = str(
                self._candidate_dir(candidate) / "search_report.html")
            return True
        if record.get("status") == "failed":
            candidate["status"] = "failed"
            candidate["reason"] = record.get("reason", "solver failed")
            state["accounting"]["failed_evaluations"] += 1
            return True
        return False

    def execute_pending(self, *, dry_run: bool = False) -> dict[str, Any]:
        state = self.initialize()
        pending = [
            row for row in state["candidates"]
            if row["status"] in {
                "proposed", "running", "interrupted", "dry-run",
            }
        ][:4]
        if not pending:
            self.render_report(state)
            return state
        library = {
            row["coordinate_hash"]: row for row in self._library({
                candidate["coordinate_hash"] for candidate in pending
                if not candidate.get("force_new_evaluation")
            })
            if row.get("coordinate_hash")
        }
        searches: list[Path] = []
        charged: list[dict[str, Any]] = []
        for candidate in pending:
            if candidate["status"] in {"running", "interrupted"}:
                if self._harvest(state, candidate):
                    continue
                state["accounting"]["interrupted_retries"] += 1
            if (
                not candidate.get("force_new_evaluation")
                and candidate["coordinate_hash"] in library
            ):
                evidence = library[candidate["coordinate_hash"]]
                project_path, search_path, _project = self.materialize(candidate)
                candidate.update({
                    "status": "reused",
                    "surface_score_v2_3":
                        float(evidence["surface_score_v2_3"]),
                    "throat_impedance_score_v2_3_0":
                        float(evidence["throat_impedance_score_v2_3_0"]),
                    "response_path": evidence.get("response_path"),
                    "nearest_evidence": evidence.get(
                        "project_path", evidence.get("response_path")),
                    "project_path": str(project_path),
                    "search_path": str(search_path),
                })
                state["accounting"]["exact_library_reuses"] += 1
                continue
            project_path, search_path, _project = self.materialize(candidate)
            if candidate["status"] == "geometry-rejected":
                state["accounting"]["geometry_rejections"] += 1
                continue
            # Export/preflight before spending a simulation.
            preflight = run_search(
                search_path, search_path.parent, binary=None, dry_run=True)
            preflight_candidate = (preflight.get("candidates") or [{}])[0]
            if preflight_candidate.get("status") != "preflight":
                candidate["status"] = "geometry-rejected"
                candidate["reason"] = preflight_candidate.get(
                    "reason", "geometry preflight failed")
                state["accounting"]["geometry_rejections"] += 1
                continue
            candidate["project_path"] = str(project_path)
            candidate["search_path"] = str(search_path)
            if dry_run:
                candidate["status"] = "dry-run"
                continue
            if (
                candidate["status"] not in {"running", "interrupted"}
                and state["accounting"]["solver_evaluations"]
                >= self.config.max_simulations
            ):
                candidate["status"] = "budget-blocked"
                continue
            if candidate["status"] not in {"running", "interrupted"}:
                state["accounting"]["solver_evaluations"] += 1
                candidate["evaluation_number"] = (
                    state["accounting"]["solver_evaluations"])
                if candidate["branch"] == "final-confirmation":
                    state["accounting"]["confirmation_evaluations"] += 1
            candidate["status"] = "running"
            searches.append(search_path)
            charged.append(candidate)
        self.save_state(state)
        self.render_report(state)
        if searches:
            runtime = self.output / (
                f"round-{charged[0]['round']:02d}-runtime.json")
            stop_refresh = threading.Event()

            def refresh_while_running() -> None:
                while not stop_refresh.wait(3):
                    self._refresh_from_disk()

            refresher = threading.Thread(
                target=refresh_while_running,
                name="horn-optimizer-report-refresher",
                daemon=True,
            )
            refresher.start()
            try:
                runtime_result = self.queue_runner(
                    searches,
                    runtime,
                    queue_workers=min(4, len(searches)),
                    numcalc_processes=20,
                    on_event=lambda _event: self._refresh_from_disk(),
                )
                retries = sum(
                    max(0, len(event.get("attempts", []))-1)
                    for event in runtime_result.get("events", [])
                )
                state["accounting"]["solver_recovery_retries"] += retries
                state["rounds"][-1]["runtime_path"] = str(runtime)
                state["rounds"][-1]["solver_recovery_retries"] = retries
            except Exception:
                for candidate in charged:
                    if not self._harvest(state, candidate):
                        candidate["status"] = "interrupted"
                self.save_state(state)
                self.render_report(state)
                raise
            finally:
                stop_refresh.set()
                refresher.join()
            for candidate in charged:
                if not self._harvest(state, candidate):
                    candidate["status"] = "interrupted"
        if not dry_run:
            self._close_round(state)
        self.save_state(state)
        self.render_report(state)
        self._write_outputs(state)
        return state

    def _refresh_from_disk(self) -> None:
        if self.state_path.is_file():
            state = _read_json(self.state_path)
            changed = False
            for candidate in state["candidates"]:
                if candidate["status"] == "running":
                    changed = self._harvest(state, candidate) or changed
            if changed:
                self.save_state(state)
            self.render_report(state)

    def ranking(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        rule = self.config.ranking
        return rank_measurements(
            state["candidates"],
            shortlist_points=rule.surface_shortlist_points,
            tie_break=rule.tie_break,
            enabled=rule.enabled,
        )

    def _close_round(self, state: dict[str, Any]) -> None:
        if not state["rounds"]:
            return
        latest = state["rounds"][-1]
        rows = [
            row for row in state["candidates"]
            if row["proposal_hash"] in latest["proposal_hashes"]
        ]
        if any(row["status"] in {
                "proposed", "awaiting_approval", "running", "interrupted",
            } for row in rows):
            return
        ranking = self.ranking(state)
        winner = ranking[0] if ranking else None
        latest["status"] = "complete"
        latest["best_after"] = winner["proposal_hash"] if winner else None
        improved = (
            winner is not None
            and winner["proposal_hash"] != latest.get("best_before")
        )
        latest["improved"] = improved
        if improved:
            state["non_improving_rounds"] = 0
        else:
            state["non_improving_rounds"] += 1
            for key in state["step_sizes"]:
                state["step_sizes"][key] *= 0.5
        steps = state["step_sizes"]
        contracted = (
            steps["length_fraction"] <= 0.02
            and steps["extension_mm"] <= 5
            and steps["k"] <= 0.25
            and steps["n"] <= 1
            and steps["mouth_mm"] <= 5
            and (
                self.config.mouth.aspect_ratio is None
                or self.config.mouth.aspect_ratio.scalar
                or steps.get("aspect_ratio", 0) <= 0.025
            )
            and steps["sag_mm"] <= 2.5
        )
        early = state["early_stopping"]
        early["contracted_local_search"] = contracted
        early["two_non_improving_rounds"] = (
            state["non_improving_rounds"] >= 2)
        if state["accounting"]["solver_evaluations"] >= self.config.max_simulations:
            state["status"] = "budget-exhausted"
            early["reason"] = "hard simulation cap reached"
        elif (
            contracted and early["two_non_improving_rounds"]
            and early["no_feasible_heuristic_branch"]
        ):
            early["reason"] = (
                "local search contracted, two rounds did not improve, and "
                "no feasible heuristic branch remains")
            if winner and not any(
                    row["branch"] == "final-confirmation"
                    for row in state["candidates"]):
                confirmation = self._candidate(
                    winner["values"], state["next_round"],
                    "final-confirmation",
                    parent_hash=winner["proposal_hash"],
                    force_new=True,
                    preserve_values=True,
                )
                confirmation["lineage"] = (
                    list(winner.get("lineage", []))
                    + [confirmation["proposal_hash"]]
                )
                state["candidates"].append(confirmation)
                state["rounds"].append({
                    "round": state["next_round"],
                    "proposal_hashes": [confirmation["proposal_hash"]],
                    "status": confirmation["status"],
                    "best_before": winner["proposal_hash"],
                    "confirmation": True,
                })
                state["next_round"] += 1
                state["status"] = "confirmation-pending"
            else:
                state["status"] = "complete"
        else:
            state["status"] = "ready"
        if winner:
            state["winner_proposal_hash"] = winner["proposal_hash"]

    def step(self, *, approve: bool = False,
             dry_run: bool = False) -> dict[str, Any]:
        state = self.initialize()
        if approve:
            self.approve()
            state = self.load_state()
        pending = [
            row for row in state["candidates"]
            if row["status"] in {
                "proposed", "awaiting_approval", "running", "interrupted",
                "dry-run",
            }
        ]
        if not pending:
            self.propose()
            state = self.load_state()
        if any(
            row["status"] == "awaiting_approval"
            for row in state["candidates"]
        ):
            return state
        return self.execute_pending(dry_run=dry_run)

    def run(self, *, approve: bool = False,
            dry_run: bool = False) -> dict[str, Any]:
        while True:
            state = self.step(approve=approve, dry_run=dry_run)
            if dry_run or state["status"] in {
                "complete", "budget-exhausted",
            }:
                return state
            if any(
                row["status"] == "awaiting_approval"
                for row in state["candidates"]
            ):
                return state

    def _write_outputs(self, state: dict[str, Any]) -> None:
        ranking = self.ranking(state)
        _write_json(self.output / "top_alternatives.json", {
            "schema_version": 1,
            "ranking_rule": self._config_snapshot()["ranking"],
            "candidates": ranking[:10],
        })
        if not ranking:
            return
        winner = ranking[0]
        state["winner_proposal_hash"] = winner["proposal_hash"]
        project = Path(str(winner.get("project_path", "")))
        if project.is_file():
            shutil.copy2(project, self.output / "winning_project.yaml")
            candidate_dir = project.parent
            stls = sorted(candidate_dir.glob("*.STL"))
            if not stls:
                try:
                    export_candidate_stl(
                        project, candidate_dir, "winning_horn")
                    stls = sorted(candidate_dir.glob("*.STL"))
                except Exception as error:
                    winner.setdefault("support_warnings", []).append(
                        f"winning STL export failed: {error}")
            if stls:
                shutil.copy2(stls[0], self.output / "winning_horn.stl")
        baseline = next((
            row for row in state["candidates"]
            if row["branch"] in {"seed-baseline", "heuristic-baseline"}
            and row.get("surface_score_v2_3") is not None
        ), None)
        _write_json(self.output / "result.json", {
            "schema_version": 1,
            "status": state["status"],
            "winner": winner,
            "seed_relative_changes": ({
                key: winner["values"][key]-baseline["values"][key]
                for key in COORDINATE_FIELDS
            } if baseline else None),
            "parameter_lineage": winner.get("lineage", []),
            "nearest_evidence": (
                winner.get("nearest_evidence")
                or winner.get("nearest_evidence_hashes", [])
            ),
            "support_warnings": (
                state.get("support_warnings", [])
                + winner.get("support_warnings", [])
            ),
            "simulation_accounting": state["accounting"],
            "early_stopping": state["early_stopping"],
        })

    def render_report(self, state: dict[str, Any] | None = None) -> Path:
        state = state or self.load_state()
        ranking = self.ranking(state)
        rank_by_hash = {
            row["proposal_hash"]: index+1
            for index, row in enumerate(ranking)
        }
        rows = []
        for candidate in state["candidates"]:
            report = candidate.get("report_path")
            label = html.escape(candidate["id"])
            if report:
                try:
                    relative = Path(report).relative_to(self.output)
                    label = f"<a href='{html.escape(str(relative))}'>{label}</a>"
                except ValueError:
                    pass
            values = candidate["values"]
            rows.append(
                "<tr>"
                f"<td data-sort-value='{candidate['id']}'>{label}</td>"
                f"<td>{candidate['round']}</td>"
                f"<td>{html.escape(candidate['branch'])}</td>"
                f"<td>{html.escape(candidate['status'])}</td>"
                f"<td>{rank_by_hash.get(candidate['proposal_hash'], '')}</td>"
                f"<td>{candidate.get('surface_score_v2_3', '')}</td>"
                f"<td>{candidate.get('throat_impedance_score_v2_3_0', '')}</td>"
                f"<td>{values['mouth_width_mm']:g}×"
                f"{values['mouth_height_mm']:g}</td>"
                f"<td>{values['length_mm']:g}</td>"
                f"<td>{values['extension_mm']:g}</td>"
                f"<td>{values['k_h']:g}/{values['k_v']:g}</td>"
                f"<td>{values['n_h']:g}/{values['n_v']:g}</td>"
                f"<td>{values['sag_mm']:g}</td>"
                "</tr>"
            )
        accounting = state["accounting"]
        warning_html = "".join(
            f"<li>{html.escape(warning)}</li>"
            for warning in state.get("support_warnings", [])
        )
        final = state["status"] in {"complete", "budget-exhausted"}
        refresh = "" if final else "<meta http-equiv='refresh' content='5'>"
        document = f"""<!doctype html>
<meta charset="utf-8">{refresh}<title>Horn optimizer</title>
<style>
body{{font:15px system-ui,sans-serif;margin:20px;background:#10161d;color:#e8edf2}}
section{{background:#17212a;border:1px solid #34414c;border-radius:9px;padding:14px;margin:14px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;min-width:max-content}}
th,td{{padding:7px 9px;border-bottom:1px solid #34414c;text-align:right}}
th{{background:#202c36;cursor:pointer;user-select:none}}
th::after{{content:" ↕";color:#83909b;font-size:.8em}}
th[aria-sort="ascending"]::after{{content:" ↑";color:#7bd7cb}}
th[aria-sort="descending"]::after{{content:" ↓";color:#7bd7cb}}
th:first-child,td:first-child{{text-align:left}}a{{color:#7bd7cb}}
</style>
<h1>Measured BEM horn optimizer</h1>
<section><strong>Status:</strong> {html.escape(state['status'])} ·
<strong>simulations:</strong> {accounting['solver_evaluations']}/
{accounting['max_simulations']} · <strong>exact reuses:</strong>
{accounting['exact_library_reuses']} · <strong>geometry rejections:</strong>
{accounting['geometry_rejections']} · <strong>updated:</strong>
{time.strftime("%Y-%m-%d %H:%M:%S %Z")}</section>
{f'<section><strong>Support warnings</strong><ul>{warning_html}</ul></section>' if warning_html else ''}
<section><table class="sortable"><thead><tr>
<th data-sort="text">Candidate</th><th data-sort="number">Round</th>
<th data-sort="text">Branch</th><th data-sort="text">Status</th>
<th data-sort="number">Rank</th><th data-sort="number">Surface v2.3</th>
<th data-sort="number">Impedance v2.3.0</th>
<th data-sort="text">Mouth W×H</th><th data-sort="number">Length</th>
<th data-sort="number">Extension</th><th data-sort="text">K H/V</th>
<th data-sort="text">N H/V</th><th data-sort="number">Sag</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<script>
document.querySelectorAll("table.sortable th[data-sort]").forEach((header, column) => {{
  header.onclick = () => {{
    const body=header.closest("table").tBodies[0], rows=Array.from(body.rows);
    const ascending=header.getAttribute("aria-sort")!=="ascending";
    header.closest("tr").querySelectorAll("th").forEach(h=>h.removeAttribute("aria-sort"));
    header.setAttribute("aria-sort",ascending?"ascending":"descending");
    rows.sort((a,b)=>{{
      const av=a.cells[column].dataset.sortValue??a.cells[column].textContent.trim();
      const bv=b.cells[column].dataset.sortValue??b.cells[column].textContent.trim();
      const comparison=header.dataset.sort==="number"
        ? (Number(av||"Infinity")-Number(bv||"Infinity"))
        : av.localeCompare(bv,undefined,{{numeric:true,sensitivity:"base"}});
      return ascending?comparison:-comparison;
    }});
    rows.forEach(row=>body.appendChild(row));
  }};
}});
</script>
"""
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / REPORT_NAME
        with self._report_lock:
            temporary = path.with_name(
                f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temporary.write_text(document, encoding="utf-8")
            temporary.replace(path)
        return path
