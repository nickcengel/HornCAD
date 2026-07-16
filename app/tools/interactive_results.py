#!/usr/bin/env python3
"""Create interactive HornCAD result and multi-project comparison reports."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yaml


COLORS = ("#2563eb", "#dc2626", "#16a34a", "#9333ea")
AIR_DENSITY_KG_M3 = 1.2041
SOUND_SPEED_M_S = 343.21
PASSBAND_CONFIRMATION_OCTAVES = 1.0 / 3.0


def _scalar(value: Any) -> Any:
    if isinstance(value, np.ndarray) and value.ndim == 0:
        return value.item()
    return value


def _source_yaml(run_dir: Path) -> Path | None:
    for filename, key in (("run_settings.json", "yaml_path"),
                          ("manifest.json", "yaml")):
        path = run_dir / filename
        if path.is_file():
            candidate = Path(json.loads(path.read_text()).get(key, ""))
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            if candidate.is_file():
                return candidate
    candidates = list(run_dir.glob("*.yaml")) + list(run_dir.glob("*.YAML"))
    if candidates:
        return candidates[0]
    for parent in run_dir.parents:
        candidate = parent / "project.yaml"
        if candidate.is_file():
            return candidate
    return None


def acoustic_parameters(yaml_path: Path | None) -> dict[str, str]:
    if yaml_path is None:
        return {}
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    g = config.get("global", {})
    h = config.get("horizontal_basis", {})
    v = config.get("vertical_basis", {})
    modifier = config.get("section_modifier", {})
    values = {
        "Length": f"{g.get('length', 0):g} mm",
        "Mouth": f"{g.get('mouth_width', 0):g} × {g.get('mouth_height', 0):g} mm",
        "Mouth sag": f"{g.get('mouth_sag', 0):g} mm",
        "Throat radius": f"{g.get('throat_radius', 0):g} mm",
        "Throat angle": f"{g.get('throat_angle_deg', 0):g}°",
        "Conical extension": f"{g.get('conical_extension_length', 0):g} mm",
        "Effective throat radius": f"{g.get('effective_throat_radius', 0):g} mm",
        "Coverage H / V": f"{h.get('coverage_deg', 0):g}° / {v.get('coverage_deg', 0):g}°",
        "K H / V": f"{h.get('k', 0):g} / {v.get('k', 0):g}",
        "N H / V": f"{h.get('n', 0):g} / {v.get('n', 0):g}",
        "S H / V": f"{h.get('solved_s', 0):.6g} / {v.get('solved_s', 0):.6g}",
        "Mouth squareness": f"{modifier.get('mouth_squareness', 0):g}",
    }
    return values


def throat_reference_impedance(yaml_path: Path | None) -> float | None:
    """Return rho*c/S for the effective circular throat."""
    if yaml_path is None:
        return None
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    global_config = config.get("global", {})
    radius_mm = global_config.get(
        "effective_throat_radius", global_config.get("throat_radius"))
    if radius_mm is None or float(radius_mm) <= 0.0:
        return None
    area_m2 = np.pi * (float(radius_mm) * 1e-3) ** 2
    return AIR_DENSITY_KG_M3 * SOUND_SPEED_M_S / area_m2


def intended_coverages(yaml_path: Path | None) -> dict[str, float]:
    if yaml_path is None:
        return {}
    config = yaml.safe_load(yaml_path.read_text())["horncad_config"]
    intent = config.get("operating_intent", {})
    return {
        "horizontal": float(intent.get("horizontal_coverage_deg",
                           config.get("horizontal_basis", {}).get("coverage_deg", 0))),
        "vertical": float(intent.get("vertical_coverage_deg",
                         config.get("vertical_basis", {}).get("coverage_deg", 0))),
    }


def load_run(run_dir: Path, name: str | None = None) -> dict[str, Any]:
    response_path = run_dir / "responses.npz"
    if not response_path.is_file():
        raise FileNotFoundError(response_path)
    with np.load(response_path, allow_pickle=False) as data:
        frequencies = np.asarray(data["frequencies_hz"], dtype=float)
        angles = np.asarray(data["angles_deg"], dtype=float)
        horizontal = np.asarray(data["horizontal_db"], dtype=float)
        vertical = np.asarray(data["vertical_db"], dtype=float)
        impedance = (np.asarray(data["impedance"], dtype=complex)
                     if "impedance" in data else None)
    yaml_path = _source_yaml(run_dir)
    reference_impedance = throat_reference_impedance(yaml_path)
    return {
        "name": name or (yaml_path.stem if yaml_path else run_dir.name),
        "run_dir": run_dir,
        "frequencies": frequencies,
        "angles": angles,
        "horizontal": horizontal,
        "vertical": vertical,
        "impedance": impedance,
        "normalized_impedance": (impedance / reference_impedance
                                 if impedance is not None and reference_impedance else None),
        "parameters": acoustic_parameters(yaml_path),
        "intended_coverages": intended_coverages(yaml_path),
        "yaml": yaml_path,
    }


def _positive_half_angle(angles: np.ndarray, levels: np.ndarray) -> np.ndarray:
    positive = angles >= 0
    a = angles[positive]
    output = []
    for row in levels[:, positive]:
        crossing = 90.0
        for index in range(len(a) - 1):
            if row[index] >= -6 and row[index + 1] < -6:
                crossing = float(a[index] + (-6 - row[index]) /
                                 (row[index + 1] - row[index]) *
                                 (a[index + 1] - a[index]))
                break
        output.append(crossing)
    return np.asarray(output)


def _measured_half_angle(angles: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Return genuine positive-side -6 dB crossings; no crossing is NaN."""
    positive = angles >= 0
    a = angles[positive]
    output = []
    for row in levels[:, positive]:
        crossing = np.nan
        for index in range(len(a) - 1):
            if row[index] >= -6 and row[index + 1] < -6:
                crossing = float(a[index] + (-6 - row[index]) /
                                 (row[index + 1] - row[index]) *
                                 (a[index + 1] - a[index]))
                break
        output.append(crossing)
    return np.asarray(output)


def coverage_diagnostics(
        run: dict[str, Any], evaluation_frequencies: np.ndarray | None = None,
        fixed_band: bool = False,
) -> dict[str, Any]:
    """Summarize coverage fidelity over an automatic or explicit common grid."""
    order = np.argsort(run["frequencies"])
    frequencies = np.asarray(run["frequencies"], dtype=float)[order]
    measured = {
        key: _measured_half_angle(run["angles"], run[key])[order]
        for key in ("horizontal", "vertical")
    }
    valid_both = np.isfinite(measured["horizontal"]) & np.isfinite(measured["vertical"])
    start_index = None
    for index in np.flatnonzero(valid_both):
        confirmation_end = frequencies[index] * 2 ** PASSBAND_CONFIRMATION_OCTAVES
        end_index = int(np.searchsorted(frequencies, confirmation_end, side="left"))
        if (end_index < len(frequencies) and end_index > index
                and np.all(valid_both[index:end_index + 1])):
            start_index = int(index)
            break
    if start_index is None and not fixed_band:
        return {"status": "unavailable",
                "reason": "no sustained horizontal and vertical -6 dB crossings"}

    # A missing crossing after the passband is established means coverage exceeded
    # the measured hemisphere. Treat it as 90 degrees instead of discarding it.
    source_start = 0 if fixed_band else start_index
    source_frequencies = frequencies[source_start:]
    source_angles = {
        key: np.where(np.isfinite(values[source_start:]), values[source_start:], 90.0)
        for key, values in measured.items()
    }
    if evaluation_frequencies is None:
        evaluated_frequencies = source_frequencies
        angles = source_angles
        band_kind = "automatic"
    else:
        evaluated_frequencies = np.asarray(evaluation_frequencies, dtype=float)
        if (evaluated_frequencies.ndim != 1 or len(evaluated_frequencies) < 2
                or np.any(np.diff(evaluated_frequencies) <= 0)):
            raise ValueError("evaluation frequencies must be an increasing 1-D grid")
        tolerance = 1e-10
        if (evaluated_frequencies[0] < source_frequencies[0] * (1 - tolerance)
                or evaluated_frequencies[-1] > source_frequencies[-1] * (1 + tolerance)):
            return {"status": "unavailable",
                    "reason": "common comparison band is outside the valid passband"}
        angles = {
            key: np.interp(np.log(evaluated_frequencies), np.log(source_frequencies), values)
            for key, values in source_angles.items()
        }
        band_kind = "fixed optimization" if fixed_band else "common comparison"
    targets = run["intended_coverages"]
    if any(targets.get(key, 0) <= 0 for key in angles):
        return {"status": "unavailable", "reason": "intended coverage is missing"}
    log_frequency = np.log(evaluated_frequencies)
    plane_results = {}
    for key, values in angles.items():
        target = float(targets[key])
        fractional_error = (values - target) / target
        coverage_error = 100 * float(np.sqrt(
            np.trapezoid(fractional_error ** 2, log_frequency) /
            (log_frequency[-1] - log_frequency[0])))
        trend = np.polyval(np.polyfit(log_frequency, values, 1), log_frequency)
        ripple_rms = float(np.sqrt(
            np.trapezoid((values - trend) ** 2, log_frequency) /
            (log_frequency[-1] - log_frequency[0])))
        narrowing = 100 * float((values[0] - values[-1]) / values[0])
        plane_results[key] = {
            "coverage_error_percent": coverage_error,
            "pattern_fit_percent": max(0.0, 100.0 - coverage_error),
            "pattern_stability_percent": max(0.0, 100.0 * (1.0 - ripple_rms / target)),
            "trend_ripple_rms_deg": ripple_rms,
            "narrowing_percent": narrowing,
            "hf_retention_percent": min(100.0, 100.0 * values[-1] / values[0]),
            "lower_half_angle_deg": float(values[0]),
            "upper_half_angle_deg": float(values[-1]),
        }
    return {
        "status": "available",
        "passband_lower_hz": float(evaluated_frequencies[0]),
        "passband_upper_hz": float(evaluated_frequencies[-1]),
        "band_kind": band_kind,
        "confirmation_octaves": PASSBAND_CONFIRMATION_OCTAVES,
        "horizontal": plane_results["horizontal"],
        "vertical": plane_results["vertical"],
        "combined": {
            "coverage_error_percent": float(np.sqrt(np.mean([
                plane_results[key]["coverage_error_percent"] ** 2 for key in plane_results]))),
            "pattern_fit_percent": max(0.0, 100.0 - float(np.sqrt(np.mean([
                plane_results[key]["coverage_error_percent"] ** 2
                for key in plane_results])))),
            "pattern_stability_percent": float(np.mean([
                plane_results[key]["pattern_stability_percent"] for key in plane_results])),
            "narrowing_percent": float(np.mean([
                plane_results[key]["narrowing_percent"] for key in plane_results])),
            "hf_retention_percent": float(np.mean([
                plane_results[key]["hf_retention_percent"] for key in plane_results])),
        },
    }


def comparison_diagnostics(runs: list[dict[str, Any]]) -> tuple[dict[str, Any], np.ndarray]:
    """Recompute all run diagnostics on one shared logarithmic frequency grid."""
    automatic = [coverage_diagnostics(run) for run in runs]
    unavailable = [item for item in automatic if item["status"] != "available"]
    if unavailable:
        raise ValueError("cannot establish comparison passband: " +
                         "; ".join(item["reason"] for item in unavailable))
    lower = max(item["passband_lower_hz"] for item in automatic)
    upper = min(item["passband_upper_hz"] for item in automatic)
    if upper <= lower:
        raise ValueError("compared runs have no overlapping valid passband")
    intervals = max(2, int(np.ceil(np.log2(upper / lower) * 48)))
    grid = np.geomspace(lower, upper, intervals + 1)
    diagnostics = {
        run["name"]: coverage_diagnostics(run, grid) for run in runs
    }
    return diagnostics, grid


def _frequency_axis(frequencies: np.ndarray) -> dict[str, Any]:
    minimum = float(np.min(frequencies))
    maximum = float(np.max(frequencies))
    tick_values = []
    for exponent in range(int(np.floor(np.log10(minimum))) - 1,
                          int(np.ceil(np.log10(maximum))) + 1):
        for multiplier in (1, 2, 5):
            value = multiplier * 10.0 ** exponent
            if minimum * (1 - 1e-12) <= value <= maximum * (1 + 1e-12):
                tick_values.append(value)
    for endpoint in (minimum, maximum):
        if not any(np.isclose(endpoint, value, rtol=1e-12) for value in tick_values):
            tick_values.append(endpoint)
    tick_values.sort()
    tick_text = [f"{value / 1000:g}k" if value >= 1000 else f"{value:g}"
                 for value in tick_values]
    return {
        "type": "log", "title_text": "Frequency (Hz)",
        "tickmode": "array", "tickvals": tick_values, "ticktext": tick_text,
        "ticks": "outside", "ticklen": 6,
        "showgrid": True, "gridcolor": "rgba(70,85,110,0.34)",
        "gridwidth": 1.2, "zeroline": False,
        "minor": {"dtick": "D1", "ticks": "inside", "ticklen": 3,
                  "showgrid": True, "gridcolor": "rgba(70,85,110,0.14)",
                  "griddash": "dot"},
    }


def _frequency_grid_values(frequencies: np.ndarray) -> tuple[list[float], list[float]]:
    axis = _frequency_axis(frequencies)
    major = [float(value) for value in axis["tickvals"]]
    minimum = float(np.min(frequencies))
    maximum = float(np.max(frequencies))
    fine = []
    for exponent in range(int(np.floor(np.log10(minimum))) - 1,
                          int(np.ceil(np.log10(maximum))) + 1):
        for multiplier in range(1, 10):
            value = multiplier * 10.0 ** exponent
            if (minimum < value < maximum and
                    not any(np.isclose(value, tick, rtol=1e-12) for tick in major)):
                fine.append(value)
    return major, fine


def _parameter_table(runs: list[dict[str, Any]]) -> str:
    keys = list(dict.fromkeys(key for run in runs for key in run["parameters"]))
    header = "<tr><th>Parameter</th>" + "".join(
        f"<th style='color:{COLORS[i]}'>{html.escape(run['name'])}</th>"
        for i, run in enumerate(runs)) + "</tr>"
    rows = "".join("<tr><td>" + html.escape(key) + "</td>" + "".join(
        f"<td>{html.escape(run['parameters'].get(key, '—'))}</td>" for run in runs)
        + "</tr>" for key in keys)
    return f"<table>{header}{rows}</table>"


DIAGNOSTIC_ROWS = (("Pattern Fit", "pattern_fit_percent"),
                   ("Pattern Stability", "pattern_stability_percent"),
                   ("HF Retention", "hf_retention_percent"))


def _score_cell(value: float) -> str:
    strength = "strong" if value >= 80 else "moderate" if value >= 60 else "weak"
    return (f"<td class='score {strength}'><span>{value:.1f}%</span>"
            f"<i style='width:{value:.1f}%'></i></td>")


def _diagnostic_tables(runs: list[dict[str, Any]],
                       diagnostics: dict[str, Any], comparison: bool) -> str:
    first = diagnostics[runs[0]["name"]]
    if first["status"] != "available":
        return f"<p>{html.escape(first['reason'])}</p>"
    band = f"{first['passband_lower_hz']:g}–{first['passband_upper_hz']:g} Hz"
    if comparison:
        sections = []
        header = "<th>Diagnostic</th>" + "".join(
            f"<th style='color:{COLORS[index]}'>{html.escape(run['name'])}</th>"
            for index, run in enumerate(runs))
        for label, plane in (("Combined", "combined"), ("Horizontal", "horizontal"),
                             ("Vertical", "vertical")):
            rows = "".join(
                f"<tr><th>{name}</th>" + "".join(
                    _score_cell(diagnostics[run["name"]][plane][key]) for run in runs) +
                "</tr>" for name, key in DIAGNOSTIC_ROWS)
            sections.append(f"<div class='diagnostic-card'><h3>{label}</h3>"
                            f"<table><tr>{header}</tr>{rows}</table></div>")
        return (f"<p class='diagnostic-band'><strong>Common evaluated band:</strong> "
                f"{band}</p><div class='diagnostic-grid'>{''.join(sections)}</div>")

    diagnostic = first
    header = "<th>Diagnostic</th><th>Combined</th><th>Horizontal</th><th>Vertical</th>"
    rows = "".join(
        f"<tr><th>{name}</th>" + "".join(
            _score_cell(diagnostic[plane][key])
            for plane in ("combined", "horizontal", "vertical")) + "</tr>"
        for name, key in DIAGNOSTIC_ROWS)
    return (f"<p class='diagnostic-band'><strong>Evaluated band:</strong> {band}</p>"
            f"<table><tr>{header}</tr>{rows}</table>")


def _write_html(path: Path, title: str, figure: go.Figure,
                runs: list[dict[str, Any]], diagnostics: dict[str, Any] | None = None,
                comparison: bool = False) -> Path:
    if diagnostics is None:
        diagnostics = {run["name"]: coverage_diagnostics(run) for run in runs}
    band_explanation = (
        "Comparison values are recomputed on one shared 48-point-per-octave "
        "log-frequency grid over the overlapping valid passband."
        if comparison else
        "The automatic passband starts after both planes sustain genuine −6 dB "
        "crossings for one-third octave."
    )
    plot = figure.to_html(full_html=False, include_plotlyjs=True,
                          config={"displaylogo": False, "scrollZoom": True,
                                  "responsive": True})
    document = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>{html.escape(title)}</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#172033}}
main{{max-width:1500px;margin:auto;padding:18px}} h1{{margin:0 0 12px}}
.plot,.parameters{{background:white;border:1px solid #d8dde7;border-radius:10px;padding:12px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:7px 10px;border-bottom:1px solid #e4e7ed;text-align:left}}
th{{background:#f1f3f7;position:sticky;top:0}} .hint{{color:#566176;margin:0 0 12px}}
.diagnostic-band{{font-size:1.05rem}} .diagnostic-grid{{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:14px}}
.diagnostic-card{{border:1px solid #d8dde7;border-radius:8px;padding:0 10px 10px}} .diagnostic-card h3{{margin:10px 0}}
.score{{position:relative;min-width:85px}} .score span{{position:relative;z-index:1;font-variant-numeric:tabular-nums}}
.score i{{position:absolute;left:0;bottom:2px;height:4px;border-radius:2px;background:#64748b}}
.score.strong i{{background:#16856b}} .score.moderate i{{background:#b7791f}} .score.weak i{{background:#b45353}}
@media(max-width:950px){{.diagnostic-grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>{html.escape(title)}</h1>
<p class='hint'>Hover for exact coordinates. Drag to zoom; double-click to reset; use the legend to hide traces.</p>
<section class='plot'>{plot}</section><section class='parameters'><h2>Horn acoustic parameters</h2>
{_parameter_table(runs)}</section><section class='parameters'><h2>Coverage diagnostics</h2>
{_diagnostic_tables(runs, diagnostics, comparison)}
<p class='hint'>All three diagnostics are percentages where 100% is ideal. Pattern Fit is 100% minus the log-frequency-weighted RMS percentage error from the intended −6 dB half-angle. Pattern Stability is 100% minus RMS deviation from the best-fit straight line versus log frequency, normalized by intended coverage. HF Retention is the upper-bound half-angle divided by the lower-bound half-angle, capped at 100%. {band_explanation}</p>
</section></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document)
    diagnostics_path = path.with_name("coverage_diagnostics.json")
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
    return path


def single_report(run_dir: Path, output: Path | None = None,
                  title: str | None = None) -> Path:
    run = load_run(run_dir)
    figure = make_subplots(rows=2, cols=2,
                           specs=[[{}, {}], [{"colspan": 2}, None]],
                           subplot_titles=("Horizontal coverage", "Vertical coverage",
                                           "Normalized throat impedance magnitude"),
                           vertical_spacing=.12)
    for column, key in enumerate(("horizontal", "vertical"), 1):
        figure.add_trace(go.Heatmap(
            x=run["frequencies"], y=run["angles"], z=run[key].T,
            coloraxis="coloraxis",
            hovertemplate="%{x:.1f} Hz<br>%{y:.1f}°<br>%{z:.2f} dB<extra></extra>"),
            row=1, col=column)
        figure.add_trace(go.Contour(
            x=run["frequencies"], y=run["angles"], z=run[key].T,
            contours={"start": -6, "end": -6, "size": 1, "coloring": "lines",
                      "showlabels": True, "labelfont": {"color": "white"}},
            line={"color": "white", "width": 3}, showscale=False,
            name=f"{key.title()} −6 dB", showlegend=True,
            hoverinfo="skip"),
            row=1, col=column)
        intended = run["intended_coverages"].get(key)
        if intended:
            start, stop = run["frequencies"][[0, -1]]
            figure.add_trace(go.Scatter(
                x=[start, stop, None, start, stop],
                y=[intended, intended, None, -intended, -intended],
                mode="lines", name=f"{key.title()} intended coverage ±{intended:g}°",
                line={"color": "#00ffff", "width": 3, "dash": "dash"},
                hoverinfo="skip"),
                row=1, col=column)
    if run["normalized_impedance"] is not None:
        figure.add_trace(go.Scatter(
            x=run["frequencies"], y=np.abs(run["normalized_impedance"]), mode="lines",
            name="|Z throat| / (ρc/Sₜ)", line={"width": 2.5},
            hovertemplate="%{x:.1f} Hz<br>%{y:.4g}<extra></extra>"),
            row=2, col=1)
    major_frequencies, fine_frequencies = _frequency_grid_values(run["frequencies"])
    for column in (1, 2):
        for frequency in fine_frequencies:
            figure.add_vline(
                x=frequency, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.30)", "width": .8,
                      "dash": "dot"})
        for frequency in major_frequencies:
            figure.add_vline(
                x=frequency, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.52)", "width": 1.2})
        for angle in (-90, -60, -30, 0, 30, 60, 90):
            figure.add_hline(
                y=angle, row=1, col=column, layer="above",
                line={"color": "rgba(255,255,255,0.48)",
                      "width": 1.4 if angle == 0 else 1.0})
    figure.update_xaxes(**_frequency_axis(run["frequencies"]))
    figure.update_yaxes(
        title_text="Off-axis angle (degrees)", row=1,
        tickmode="array", tickvals=[-90, -60, -30, 0, 30, 60, 90],
        ticks="outside", ticklen=6, showgrid=True,
        gridcolor="rgba(70,85,110,0.30)", gridwidth=1.2, zeroline=True,
        zerolinecolor="rgba(30,45,70,0.55)", zerolinewidth=1.5)
    figure.update_yaxes(title_text="|Z| / (ρc/Sₜ)", row=2, col=1)
    figure.update_layout(
        height=1000, hovermode="closest",
        coloraxis={"cmin": -30, "cmax": 0, "colorscale": "Turbo",
                   "colorbar": {"title": "dB", "x": 1.015, "y": .78,
                                "len": .42, "thickness": 16}},
        legend={"orientation": "h", "x": 0, "xanchor": "left",
                "y": 1.12, "yanchor": "bottom"},
        margin={"t": 145, "r": 95, "b": 75, "l": 80})
    return _write_html(output or run_dir / "interactive_report.html",
                       title or run["name"], figure, [run])


def comparison_report(run_dirs: list[Path], output: Path,
                      names: list[str] | None = None,
                      title: str = "Horn comparison",
                      evaluation_frequencies: np.ndarray | None = None,
                      fixed_band: bool = False) -> Path:
    if not 2 <= len(run_dirs) <= 4:
        raise ValueError("comparison requires two to four runs")
    if names is not None and len(names) != len(run_dirs):
        raise ValueError("--names must contain one name per run")
    runs = [load_run(path, names[i] if names else None)
            for i, path in enumerate(run_dirs)]
    figure = make_subplots(rows=1, cols=3,
                           subplot_titles=("Horizontal −6 dB half-angle",
                                           "Vertical −6 dB half-angle",
                                           "Normalized throat impedance magnitude"))
    for index, run in enumerate(runs):
        color = COLORS[index]
        for column, key in enumerate(("horizontal", "vertical"), 1):
            figure.add_trace(go.Scatter(
                x=run["frequencies"],
                y=_positive_half_angle(run["angles"], run[key]),
                mode="lines+markers", name=run["name"], legendgroup=run["name"],
                showlegend=column == 1, line={"color": color, "width": 2.5},
                hovertemplate="%{x:.1f} Hz<br>%{y:.2f}°<extra>" +
                              html.escape(run["name"]) + "</extra>"), row=1, col=column)
        if run["normalized_impedance"] is not None:
            figure.add_trace(go.Scatter(
                x=run["frequencies"], y=np.abs(run["normalized_impedance"]), mode="lines",
                name=run["name"], legendgroup=run["name"], showlegend=False,
                line={"color": color, "width": 2.5},
                hovertemplate="%{x:.1f} Hz<br>%{y:.4g}<extra>" +
                              html.escape(run["name"]) + "</extra>"), row=1, col=3)
    all_frequencies = np.concatenate([run["frequencies"] for run in runs])
    figure.update_xaxes(**_frequency_axis(all_frequencies))
    figure.update_yaxes(title_text="Half-angle (degrees)", range=[0, 90], row=1, col=1)
    figure.update_yaxes(title_text="Half-angle (degrees)", range=[0, 90], row=1, col=2)
    figure.update_yaxes(title_text="|Z| / (ρc/Sₜ)", row=1, col=3)
    figure.update_layout(height=620, hovermode="closest", legend={"orientation": "h"})
    if evaluation_frequencies is None:
        diagnostics, _ = comparison_diagnostics(runs)
    else:
        diagnostics = {run["name"]: coverage_diagnostics(
            run, evaluation_frequencies, fixed_band=fixed_band) for run in runs}
    return _write_html(output, title, figure, runs, diagnostics, comparison=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("run_dir", type=Path)
    report.add_argument("--output", type=Path)
    report.add_argument("--title")
    compare = subparsers.add_parser("compare")
    compare.add_argument("run_dirs", nargs="+", type=Path)
    compare.add_argument("--output", required=True, type=Path)
    compare.add_argument("--names", nargs="+")
    compare.add_argument("--title", default="Horn comparison")
    args = parser.parse_args()
    if args.command == "report":
        print(single_report(args.run_dir, args.output, args.title))
    else:
        print(comparison_report(args.run_dirs, args.output, args.names, args.title))


if __name__ == "__main__":
    main()
