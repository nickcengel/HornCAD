#!/usr/bin/env python3
"""Run a lossless one-dimensional Webster-horn analysis for a HornCAD design."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math

import numpy as np
from scipy.special import j1, struve

try:
    from . import export_horncad as geometry
except ImportError:
    import export_horncad as geometry


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
MM_TO_M = 1e-3
MM2_TO_M2 = 1e-6
GEOMETRY_DEFAULTS = copy.deepcopy(geometry.PARAMS)
DEFAULT_Z_STATIONS = geometry.Z_STATIONS
DEFAULT_SIDE_SAMPLES = geometry.SIDE_SAMPLES


@dataclass(frozen=True)
class Medium:
    density_kg_m3: float = 1.2041
    sound_speed_m_s: float = 343.21


@dataclass(frozen=True)
class AreaProfile:
    positions_m: np.ndarray
    areas_m2: np.ndarray
    s_horizontal: float
    s_vertical: float

    def validate(self) -> None:
        if len(self.positions_m) < 2 or len(self.positions_m) != len(self.areas_m2):
            raise ValueError("area profile needs matching position and area arrays with at least two stations")
        if not np.all(np.isfinite(self.positions_m)) or not np.all(np.isfinite(self.areas_m2)):
            raise ValueError("area profile contains non-finite values")
        if not np.all(np.diff(self.positions_m) > 0.0):
            raise ValueError("area profile positions must be strictly increasing")
        if not np.all(self.areas_m2 > 0.0):
            raise ValueError("area profile contains a non-positive section")
        area_tolerance = max(float(np.max(self.areas_m2)) * 1e-9, 1e-15)
        if np.any(np.diff(self.areas_m2) < -area_tolerance):
            raise ValueError("area profile is not monotonically expanding")
        if not math.isfinite(self.s_horizontal) or not math.isfinite(self.s_vertical):
            raise ValueError("derived S must be finite on both axes")
        if self.s_horizontal < 0.0 or self.s_vertical < 0.0:
            raise ValueError(
                f"invalid profile: derived S must be nonnegative "
                f"(horizontal={self.s_horizontal:.6g}, vertical={self.s_vertical:.6g})"
            )


@dataclass(frozen=True)
class FrequencyResult:
    frequency_hz: float
    input_impedance_pa_s_m3: complex
    throat_reflection: complex
    mouth_pressure_pa_per_m3_s: complex
    mouth_volume_velocity_ratio: complex
    radiated_power_w_per_m3_s_sq: float


def polygon_area_xy(points: list[tuple[float, float, float]]) -> float:
    """Return projected XY polygon area in the input coordinate units squared."""
    return 0.5 * abs(
        sum(
            point[0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * point[1]
            for index, point in enumerate(points)
        )
    )


def derived_s_values() -> tuple[float, float]:
    effective_r0 = geometry.effective_throat_radius()
    common = (geometry.PARAMS["length"], effective_r0)
    horizontal = geometry.solved_s(
        *common,
        geometry.PARAMS["h_coverage"],
        geometry.PARAMS["h_k"],
        geometry.PARAMS["h_n"],
        geometry.PARAMS["mouth_width"] / 2.0,
        geometry.PARAMS["throat_angle"],
    )
    vertical = geometry.solved_s(
        *common,
        geometry.PARAMS["v_coverage"],
        geometry.PARAMS["v_k"],
        geometry.PARAMS["v_n"],
        geometry.PARAMS["mouth_height"] / 2.0,
        geometry.PARAMS["throat_angle"],
    )
    return horizontal, vertical


def horncad_area_profile(yaml_path: Path, station_count: int = 401) -> AreaProfile:
    """Sample HornCAD's acoustic sections as an area-versus-distance profile."""
    if station_count < 3:
        raise ValueError("station_count must be at least 3")

    geometry.PARAMS.clear()
    geometry.PARAMS.update(copy.deepcopy(GEOMETRY_DEFAULTS))
    geometry.Z_STATIONS = DEFAULT_Z_STATIONS
    geometry.SIDE_SAMPLES = DEFAULT_SIDE_SAMPLES
    geometry.apply_horncad_yaml(yaml_path)
    s_horizontal, s_vertical = derived_s_values()
    if s_horizontal < 0.0 or s_vertical < 0.0:
        raise ValueError(
            f"invalid profile: derived S must be nonnegative "
            f"(horizontal={s_horizontal:.6g}, vertical={s_vertical:.6g})"
        )

    extension_mm = max(0.0, float(geometry.PARAMS["throat_extension"]))
    profile_length_mm = float(geometry.PARAMS["length"])
    total_length_mm = extension_mm + profile_length_mm
    if total_length_mm <= 0.0 or profile_length_mm <= 0.0:
        raise ValueError("horn length must be positive")

    h_profile = geometry.profile("h")
    v_profile = geometry.profile("v")
    mouth_h = h_profile(profile_length_mm)
    mouth_v = v_profile(profile_length_mm)
    positions_mm = np.linspace(0.0, total_length_mm, station_count)
    areas_mm2 = np.empty(station_count, dtype=float)

    for index, position_mm in enumerate(positions_mm):
        if extension_mm > 0.0 and position_mm < extension_mm:
            ring = geometry.conical_extension_ring(position_mm / extension_mm)
        else:
            profile_z = min(profile_length_mm, max(0.0, position_mm - extension_mm))
            tau = profile_z / profile_length_mm
            ring = geometry.ring_at(
                tau,
                h_profile(profile_z),
                v_profile(profile_z),
                mouth_h,
                mouth_v,
            )
        areas_mm2[index] = polygon_area_xy(ring)

    result = AreaProfile(
        positions_m=positions_mm * MM_TO_M,
        areas_m2=areas_mm2 * MM2_TO_M2,
        s_horizontal=s_horizontal,
        s_vertical=s_vertical,
    )
    result.validate()
    return result


def equivalent_radius(area_m2: float) -> float:
    return math.sqrt(area_m2 / math.pi)


def mouth_load_impedance(
    frequency_hz: float,
    area_m2: float,
    medium: Medium,
    load: str,
) -> complex:
    """Return pressure/volume-velocity load impedance at the mouth."""
    characteristic = medium.density_kg_m3 * medium.sound_speed_m_s / area_m2
    if load == "anechoic":
        return complex(characteristic)
    if load != "baffled_piston":
        raise ValueError(f"unknown mouth load: {load}")

    wave_number = 2.0 * math.pi * frequency_hz / medium.sound_speed_m_s
    ka = wave_number * equivalent_radius(area_m2)
    if ka <= 1e-12:
        return 0.0j
    normalized_resistance = 1.0 - j1(2.0 * ka) / ka
    normalized_reactance = struve(1, 2.0 * ka) / ka
    return characteristic * complex(normalized_resistance, normalized_reactance)


def solve_frequency(
    profile: AreaProfile,
    frequency_hz: float,
    medium: Medium = Medium(),
    mouth_load: str = "baffled_piston",
) -> FrequencyResult:
    """Cascade locally uniform ducts and solve for unit throat volume velocity."""
    profile.validate()
    if frequency_hz <= 0.0 or not math.isfinite(frequency_hz):
        raise ValueError("frequency must be finite and greater than zero")
    if medium.density_kg_m3 <= 0.0 or medium.sound_speed_m_s <= 0.0:
        raise ValueError("medium density and sound speed must be positive")

    wave_number = 2.0 * math.pi * frequency_hz / medium.sound_speed_m_s
    matrix = np.eye(2, dtype=complex)
    for index, length_m in enumerate(np.diff(profile.positions_m)):
        area_m2 = math.sqrt(profile.areas_m2[index] * profile.areas_m2[index + 1])
        characteristic = medium.density_kg_m3 * medium.sound_speed_m_s / area_m2
        phase = wave_number * length_m
        segment = np.array(
            [
                [math.cos(phase), 1j * characteristic * math.sin(phase)],
                [1j * math.sin(phase) / characteristic, math.cos(phase)],
            ],
            dtype=complex,
        )
        matrix = matrix @ segment

    load = mouth_load_impedance(
        frequency_hz,
        float(profile.areas_m2[-1]),
        medium,
        mouth_load,
    )
    denominator = matrix[1, 0] * load + matrix[1, 1]
    if abs(denominator) <= 1e-18:
        raise ValueError(f"singular Webster transfer matrix at {frequency_hz:g} Hz")
    mouth_velocity = 1.0 / denominator
    mouth_pressure = load * mouth_velocity
    input_pressure = matrix[0, 0] * mouth_pressure + matrix[0, 1] * mouth_velocity
    input_impedance = input_pressure  # Unit throat volume velocity.
    throat_characteristic = (
        medium.density_kg_m3 * medium.sound_speed_m_s / float(profile.areas_m2[0])
    )
    reflection = (input_impedance - throat_characteristic) / (
        input_impedance + throat_characteristic
    )
    radiated_power = max(0.0, 0.5 * abs(mouth_velocity) ** 2 * load.real)
    return FrequencyResult(
        frequency_hz=frequency_hz,
        input_impedance_pa_s_m3=input_impedance,
        throat_reflection=reflection,
        mouth_pressure_pa_per_m3_s=mouth_pressure,
        mouth_volume_velocity_ratio=mouth_velocity,
        radiated_power_w_per_m3_s_sq=radiated_power,
    )


def frequency_grid(start_hz: float, stop_hz: float, count: int, spacing: str) -> np.ndarray:
    if start_hz <= 0.0 or stop_hz <= start_hz:
        raise ValueError("frequency range must satisfy 0 < start < stop")
    if count < 2:
        raise ValueError("frequency count must be at least 2")
    if spacing == "log":
        return np.geomspace(start_hz, stop_hz, count)
    if spacing == "linear":
        return np.linspace(start_hz, stop_hz, count)
    raise ValueError(f"unknown frequency spacing: {spacing}")


def solve_sweep(
    profile: AreaProfile,
    frequencies_hz: np.ndarray,
    medium: Medium = Medium(),
    mouth_load: str = "baffled_piston",
) -> list[FrequencyResult]:
    return [
        solve_frequency(profile, float(frequency), medium, mouth_load)
        for frequency in frequencies_hz
    ]


def complex_parts(value: complex, prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_real": float(value.real),
        f"{prefix}_imag": float(value.imag),
        f"{prefix}_magnitude": float(abs(value)),
        f"{prefix}_phase_deg": float(math.degrees(math.atan2(value.imag, value.real))),
    }


def result_row(result: FrequencyResult) -> dict[str, float]:
    row = {"frequency_hz": result.frequency_hz}
    row.update(complex_parts(result.input_impedance_pa_s_m3, "input_impedance_pa_s_m3"))
    row.update(complex_parts(result.throat_reflection, "throat_reflection"))
    row.update(complex_parts(result.mouth_pressure_pa_per_m3_s, "mouth_pressure_pa_per_m3_s"))
    row.update(complex_parts(result.mouth_volume_velocity_ratio, "mouth_volume_velocity_ratio"))
    row["radiated_power_w_per_m3_s_sq"] = result.radiated_power_w_per_m3_s_sq
    return row


def write_results(
    yaml_path: Path,
    output_dir: Path,
    profile: AreaProfile,
    results: list[FrequencyResult],
    medium: Medium,
    mouth_load: str,
) -> tuple[Path, Path, Path, Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{yaml_path.stem}-Webster1D"
    csv_path = output_dir / f"{stem}.csv"
    area_path = output_dir / f"{stem}-Area.csv"
    plot_path = output_dir / f"{stem}-Normalized-Impedance.png"
    summary_path = output_dir / f"{stem}.json"

    rows = [result_row(result) for result in results]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with area_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("position_m", "area_m2", "equivalent_radius_m"))
        for position, area in zip(profile.positions_m, profile.areas_m2):
            writer.writerow((float(position), float(area), equivalent_radius(float(area))))

    reflection_magnitudes = np.array([abs(result.throat_reflection) for result in results])
    throat_characteristic = (
        medium.density_kg_m3 * medium.sound_speed_m_s / float(profile.areas_m2[0])
    )
    frequencies = np.array([result.frequency_hz for result in results])
    normalized_impedance = np.array(
        [result.input_impedance_pa_s_m3 / throat_characteristic for result in results]
    )
    figure, axis = plt.subplots(figsize=(10.5, 6.25), constrained_layout=True)
    axis.semilogx(frequencies, normalized_impedance.real, label="Resistance Re(Zin/Z0)", linewidth=1.8)
    axis.semilogx(frequencies, normalized_impedance.imag, label="Reactance Im(Zin/Z0)", linewidth=1.5)
    axis.semilogx(frequencies, np.abs(normalized_impedance), label="Magnitude |Zin/Z0|", linewidth=1.8)
    axis.axhline(0.0, color="black", linewidth=0.7, alpha=0.55)
    axis.axhline(1.0, color="black", linewidth=0.7, alpha=0.3, linestyle="--")
    axis.set_title("HornCAD Webster 1D — Normalized Throat Input Impedance")
    axis.set_xlabel("Frequency (Hz)")
    axis.set_ylabel("Normalized impedance")
    axis.grid(True, which="both", alpha=0.25)
    axis.legend()
    figure.savefig(plot_path, dpi=180)
    plt.close(figure)

    peak_index = int(np.argmax(reflection_magnitudes))
    summary = {
        "model": "lossless_webster_1d",
        "source_yaml": str(yaml_path),
        "assumptions": [
            "plane waves",
            "lossless rigid walls",
            "projected cross-sectional area",
            "locally uniform transmission-line segments",
        ],
        "mouth_load": mouth_load,
        "medium": asdict(medium),
        "station_count": len(profile.positions_m),
        "length_m": float(profile.positions_m[-1] - profile.positions_m[0]),
        "throat_area_m2": float(profile.areas_m2[0]),
        "throat_characteristic_impedance_pa_s_m3": throat_characteristic,
        "mouth_area_m2": float(profile.areas_m2[-1]),
        "derived_s": {
            "horizontal": profile.s_horizontal,
            "vertical": profile.s_vertical,
        },
        "frequency": {
            "start_hz": results[0].frequency_hz,
            "stop_hz": results[-1].frequency_hz,
            "count": len(results),
        },
        "metrics": {
            "peak_reflection_magnitude": float(reflection_magnitudes[peak_index]),
            "peak_reflection_frequency_hz": results[peak_index].frequency_hz,
            "mean_reflection_magnitude": float(np.mean(reflection_magnitudes)),
        },
        "artifacts": {
            "frequency_response_csv": str(csv_path),
            "area_profile_csv": str(area_path),
            "normalized_impedance_plot": str(plot_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return csv_path, area_path, plot_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml", type=Path, help="HornCAD YAML exported by the browser app.")
    parser.add_argument("--start-hz", type=float, default=100.0)
    parser.add_argument("--stop-hz", type=float, default=20_000.0)
    parser.add_argument("--frequencies", type=int, default=241)
    parser.add_argument("--spacing", choices=("log", "linear"), default="log")
    parser.add_argument("--stations", type=int, default=401)
    parser.add_argument(
        "--mouth-load",
        choices=("baffled_piston", "anechoic"),
        default="baffled_piston",
    )
    parser.add_argument("--density", type=float, default=Medium.density_kg_m3)
    parser.add_argument("--sound-speed", type=float, default=Medium.sound_speed_m_s)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    medium = Medium(args.density, args.sound_speed)
    profile = horncad_area_profile(args.yaml, args.stations)
    frequencies = frequency_grid(args.start_hz, args.stop_hz, args.frequencies, args.spacing)
    results = solve_sweep(profile, frequencies, medium, args.mouth_load)
    csv_path, area_path, plot_path, summary_path = write_results(
        args.yaml,
        args.output_dir,
        profile,
        results,
        medium,
        args.mouth_load,
    )
    print(csv_path)
    print(area_path)
    print(plot_path)
    print(summary_path)
    print(f"derived_s={profile.s_horizontal:.6g}/{profile.s_vertical:.6g}")
    print(f"sections={len(profile.positions_m)} frequencies={len(results)}")


if __name__ == "__main__":
    main()
