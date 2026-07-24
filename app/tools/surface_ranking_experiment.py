"""Build and run a blinded human-ranking experiment for coverage surfaces."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import numpy as np
import yaml


SCHEMA_VERSION = 1
DEFAULT_SEED = 20260723
BROAD_ROUND_COUNT = 10
CLOSE_ROUND_COUNT = 10
ROUND_COUNT = BROAD_ROUND_COUNT + CLOSE_ROUND_COUNT
PLOTS_PER_ROUND = 10
PLOT_ID = re.compile(r"^R\d{2}-P\d{2}$")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def _source_yaml(run_dir: Path) -> Path | None:
    candidates = sorted(run_dir.parent.glob("*.yaml"))
    if candidates:
        return candidates[0]
    candidates = sorted(run_dir.parents[1].glob("*.yaml"))
    return candidates[0] if candidates else None


def _crossover_hz(run_dir: Path, frequencies: np.ndarray) -> float:
    source = _source_yaml(run_dir)
    if source:
        config = yaml.safe_load(source.read_text()).get("horncad_config", {})
        value = config.get("operating_intent", {}).get("crossover_hz")
        if value is not None and float(value) > 0:
            return float(value)
    return float(frequencies[0])


def _candidate_report(run_dir: Path) -> Path | None:
    reports = sorted(run_dir.glob("*_Report.html"))
    return reports[0] if reports else None


def _load_candidates(index_path: Path) -> list[dict[str, Any]]:
    document = json.loads(index_path.read_text())
    rows = document["rows"] if isinstance(document, dict) else document
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        digest = row.get("response_sha256")
        score = row.get("responses", {}).get("surface_score")
        source = Path(str(row.get("source_path", "")))
        if (
            not digest
            or digest in unique
            or not isinstance(score, (int, float))
            or not np.isfinite(float(score))
            or not source.is_file()
        ):
            continue
        try:
            with np.load(source, allow_pickle=False) as data:
                required = {
                    "frequencies_hz",
                    "angles_deg",
                    "horizontal_db",
                    "vertical_db",
                }
                if not required.issubset(data.files):
                    continue
        except (OSError, ValueError):
            continue
        unique[digest] = row
    candidates = list(unique.values())
    candidates.sort(
        key=lambda row: (
            float(row["responses"]["surface_score"]),
            str(row["response_sha256"]),
        )
    )
    if len(candidates) < ROUND_COUNT * PLOTS_PER_ROUND:
        raise ValueError("fewer than 200 unique valid response archives are available")
    return candidates


def select_candidates(
    candidates: list[dict[str, Any]], seed: int = DEFAULT_SEED
) -> list[list[dict[str, Any]]]:
    """Select ten broad-range rounds followed by ten close-score rounds."""
    rng = random.Random(seed)
    bins = [list(group) for group in np.array_split(candidates, PLOTS_PER_ROUND)]
    for group in bins:
        rng.shuffle(group)
    rounds: list[list[dict[str, Any]]] = []
    for round_index in range(BROAD_ROUND_COUNT):
        selected = [group[round_index] for group in bins]
        rng.shuffle(selected)
        rounds.append(selected)
    used = {
        row["response_sha256"]
        for selected in rounds
        for row in selected
    }
    available = [
        row for row in candidates if row["response_sha256"] not in used
    ]
    all_scores = np.asarray(
        [float(row["responses"]["surface_score"]) for row in candidates]
    )
    for quantile in np.linspace(0.05, 0.95, CLOSE_ROUND_COUNT):
        target = float(np.quantile(all_scores, quantile))
        selected = sorted(
            available,
            key=lambda row: (
                abs(float(row["responses"]["surface_score"]) - target),
                str(row["response_sha256"]),
            ),
        )[:PLOTS_PER_ROUND]
        chosen = {row["response_sha256"] for row in selected}
        available = [
            row for row in available if row["response_sha256"] not in chosen
        ]
        rng.shuffle(selected)
        rounds.append(selected)
    return rounds


def _plot_surface(row: dict[str, Any], destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    colormap = LinearSegmentedColormap.from_list(
        "horncad_surface",
        [
            (0.0, "#30123b"),
            (10 / 33, "#355f8d"),
            (18 / 33, "#22a884"),
            (24 / 33, "#fde725"),
            (30 / 33, "#dc2626"),
            (1.0, "#fff7f7"),
        ],
    )
    source = Path(row["source_path"])
    coverage = float(row["coverage_deg"])
    with np.load(source, allow_pickle=False) as data:
        frequencies = np.asarray(data["frequencies_hz"], dtype=float)
        angles = np.asarray(data["angles_deg"], dtype=float)
        planes = [
            np.asarray(data["horizontal_db"], dtype=float),
            np.asarray(data["vertical_db"], dtype=float),
        ]
    order = np.argsort(frequencies)
    frequencies = frequencies[order]
    lower = max(_crossover_hz(source.parent, frequencies), float(frequencies[0]))
    keep = frequencies >= lower * (1 - 1e-12)
    frequencies = frequencies[keep]
    if len(frequencies) < 2:
        raise ValueError(f"insufficient frequencies at or above crossover: {source}")
    log_position = (
        np.log2(frequencies / frequencies[0])
        / np.log2(frequencies[-1] / frequencies[0])
    )
    normalized_angles = angles / coverage
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 2, figsize=(9.2, 3.25), sharex=True, sharey=True)
    for axis, plane, label in zip(axes, planes, ("View A", "View B"), strict=True):
        values = plane[order][keep]
        axis.pcolormesh(
            log_position,
            normalized_angles,
            values.T,
            shading="auto",
            cmap=colormap,
            vmin=-30,
            vmax=3,
            rasterized=True,
        )
        axis.contour(
            log_position,
            normalized_angles,
            values.T,
            levels=[-6],
            colors=["white"],
            linewidths=1.2,
        )
        axis.axhline(-1, color="#00ffff", linestyle="--", linewidth=1.25)
        axis.axhline(1, color="#00ffff", linestyle="--", linewidth=1.25)
        axis.axhline(0, color="white", alpha=0.35, linewidth=0.7)
        axis.set_title(label, fontsize=10)
        axis.set_xlim(0, 1)
        axis.set_ylim(-1.8, 1.8)
        axis.set_xticks([0, 0.25, 0.5, 0.75, 1])
        axis.set_yticks([-1.5, -1, -0.5, 0, 0.5, 1, 1.5])
        axis.grid(color="white", alpha=0.12, linewidth=0.5)
    axes[0].set_ylabel("Normalized angle (target edge = ±1)")
    figure.supxlabel("Normalized crossover-to-upper frequency band", fontsize=9)
    figure.tight_layout()
    figure.savefig(destination, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _initial_state(public_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": public_manifest["experiment_id"],
        "orders": {
            str(round_item["round"]): [
                plot["plot_id"] for plot in round_item["plots"]
            ]
            for round_item in public_manifest["rounds"]
        },
        "notes": {},
        "locked_rounds": [],
        "complete": False,
    }


def validate_state(
    candidate: dict[str, Any],
    public_manifest: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = {
        str(round_item["round"]): [plot["plot_id"] for plot in round_item["plots"]]
        for round_item in public_manifest["rounds"]
    }
    if candidate.get("experiment_id") != public_manifest["experiment_id"]:
        raise ValueError("experiment ID does not match")
    orders = candidate.get("orders")
    if not isinstance(orders, dict) or set(orders) != set(expected):
        raise ValueError("orders must contain every experiment round")
    for round_key, plot_ids in expected.items():
        order = orders[round_key]
        if not isinstance(order, list) or set(order) != set(plot_ids):
            raise ValueError(f"round {round_key} must contain each plot exactly once")
    all_ids = {plot_id for plot_ids in expected.values() for plot_id in plot_ids}
    notes = candidate.get("notes", {})
    if not isinstance(notes, dict) or any(plot_id not in all_ids for plot_id in notes):
        raise ValueError("notes contain an unknown plot ID")
    cleaned_notes = {}
    for plot_id, note in notes.items():
        if not isinstance(note, str):
            raise ValueError("each plot note must be text")
        cleaned_notes[plot_id] = note[:5000]
    locked = candidate.get("locked_rounds", [])
    if (
        not isinstance(locked, list)
        or any(not isinstance(value, int) for value in locked)
        or not set(locked).issubset(range(1, ROUND_COUNT + 1))
    ):
        raise ValueError("locked rounds are invalid")
    locked = sorted(set(locked))
    if previous:
        previous_locked = set(previous.get("locked_rounds", []))
        if not previous_locked.issubset(locked):
            raise ValueError("a locked round cannot be unlocked")
        for round_number in previous_locked:
            round_key = str(round_number)
            if orders[round_key] != previous["orders"][round_key]:
                raise ValueError(f"round {round_number} is already locked")
            for plot_id in expected[round_key]:
                if cleaned_notes.get(plot_id, "") != previous.get("notes", {}).get(
                    plot_id, ""
                ):
                    raise ValueError(f"notes for round {round_number} are already locked")
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": public_manifest["experiment_id"],
        "orders": orders,
        "notes": cleaned_notes,
        "locked_rounds": locked,
        "complete": len(locked) == ROUND_COUNT,
    }


def _rank_statistics(user_order: list[str], score_order: list[str]) -> dict[str, float]:
    n = len(user_order)
    score_rank = {plot_id: index + 1 for index, plot_id in enumerate(score_order)}
    squared = sum(
        ((index + 1) - score_rank[plot_id]) ** 2
        for index, plot_id in enumerate(user_order)
    )
    spearman = 1 - 6 * squared / (n * (n * n - 1))
    concordant = 0
    total = n * (n - 1) // 2
    for left in range(n):
        for right in range(left + 1, n):
            if score_rank[user_order[left]] < score_rank[user_order[right]]:
                concordant += 1
    return {
        "spearman": float(spearman),
        "pairwise_agreement": float(concordant / total),
    }


def build_report(
    root: Path, state: dict[str, Any], private_manifest: dict[str, Any]
) -> Path:
    if not state.get("complete"):
        raise ValueError("all twenty rounds must be locked before unblinding")
    mapping = private_manifest["plots"]
    sections = []
    all_squared = 0
    all_pairs = 0
    all_concordant = 0
    cohorts = {
        "Broad-range rounds 1–10": {
            "squared": 0,
            "pairs": 0,
            "concordant": 0,
            "rounds": BROAD_ROUND_COUNT,
        },
        "Close-score rounds 11–20": {
            "squared": 0,
            "pairs": 0,
            "concordant": 0,
            "rounds": CLOSE_ROUND_COUNT,
        },
    }
    for round_number in range(1, ROUND_COUNT + 1):
        cohort_name = (
            "Broad-range rounds 1–10"
            if round_number <= BROAD_ROUND_COUNT
            else "Close-score rounds 11–20"
        )
        cohort = cohorts[cohort_name]
        user_order = state["orders"][str(round_number)]
        score_order = sorted(
            user_order, key=lambda plot_id: mapping[plot_id]["surface_score"], reverse=True
        )
        stats = _rank_statistics(user_order, score_order)
        score_ranks = {plot_id: index + 1 for index, plot_id in enumerate(score_order)}
        rows = []
        for user_rank, plot_id in enumerate(user_order, 1):
            item = mapping[plot_id]
            score_rank = score_ranks[plot_id]
            squared_difference = (user_rank - score_rank) ** 2
            all_squared += squared_difference
            cohort["squared"] += squared_difference
            report_cell = html.escape(item["candidate_id"])
            if item.get("candidate_report"):
                report_cell = (
                    f"<a href='/candidate-report/{plot_id}' target='_blank'>"
                    f"{report_cell}</a>"
                )
            note = state.get("notes", {}).get(plot_id, "").strip()
            rows.append(
                "<tr>"
                f"<td>{user_rank}</td><td>{score_rank}</td>"
                f"<td>{user_rank - score_rank:+d}</td>"
                f"<td>{html.escape(plot_id)}</td><td>{report_cell}</td>"
                f"<td>{float(item['surface_score']):.2f}%</td>"
                f"<td class='note'>{html.escape(note) if note else '<span class=\"muted\">—</span>'}</td>"
                "</tr>"
            )
        pairs = PLOTS_PER_ROUND * (PLOTS_PER_ROUND - 1) // 2
        all_pairs += pairs
        concordant = round(stats["pairwise_agreement"] * pairs)
        all_concordant += concordant
        cohort["pairs"] += pairs
        cohort["concordant"] += concordant
        sections.append(
            f"<section><h2>Round {round_number}</h2>"
            f"<p>Spearman ρ: <strong>{stats['spearman']:.3f}</strong>; "
            f"pairwise agreement: <strong>{100 * stats['pairwise_agreement']:.1f}%</strong>.</p>"
            "<table><thead><tr><th>Your rank</th><th>Score rank</th>"
            "<th>Difference</th><th>Plot</th><th>Candidate report</th>"
            "<th>Current surface score</th><th>Your note</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></section>"
        )
    n = ROUND_COUNT * PLOTS_PER_ROUND
    pooled_spearman = 1 - 6 * all_squared / (n * (PLOTS_PER_ROUND**2 - 1))
    cohort_rows = []
    for name, cohort in cohorts.items():
        observations = cohort["rounds"] * PLOTS_PER_ROUND
        spearman = 1 - 6 * cohort["squared"] / (
            observations * (PLOTS_PER_ROUND**2 - 1)
        )
        agreement = cohort["concordant"] / cohort["pairs"]
        cohort_rows.append(
            f"<tr><th>{html.escape(name)}</th><td>{spearman:.3f}</td>"
            f"<td>{100 * agreement:.1f}%</td></tr>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Surface ranking experiment — comparison</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#cbd5e1;--paper:#f8fafc;--accent:#0f766e}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.45 system-ui,sans-serif}} main{{max-width:1280px;margin:auto;padding:32px}}
h1,h2{{line-height:1.15}} section{{background:white;border:1px solid var(--line);
border-radius:12px;padding:20px;margin:20px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px 10px;border-bottom:1px solid
var(--line);text-align:left;vertical-align:top}} th{{white-space:nowrap}} .note{{min-width:260px;
white-space:pre-wrap}} .muted{{color:var(--muted)}} a{{color:var(--accent)}}
</style></head><body><main><h1>Blinded surface-ranking comparison</h1>
<p>All twenty rounds are locked. Higher current surface score is treated as better.
The pooled rank statistic compares ranks within each ten-plot round.</p>
<section><h2>Overall</h2><p>Pooled within-round Spearman ρ:
<strong>{pooled_spearman:.3f}</strong>. Pairwise agreement:
<strong>{100 * all_concordant / all_pairs:.1f}%</strong>.</p>
<table><thead><tr><th>Round group</th><th>Pooled Spearman ρ</th>
<th>Pairwise agreement</th></tr></thead><tbody>{''.join(cohort_rows)}</tbody></table>
</section>
{''.join(sections)}
</main></body></html>"""
    path = root / "final_report.html"
    path.write_text(document)
    return path


def build_experiment(index_path: Path, output: Path, seed: int) -> None:
    if (output / "rankings.json").exists():
        raise FileExistsError(
            f"{output / 'rankings.json'} already exists; refusing to replace responses"
        )
    candidates = _load_candidates(index_path)
    rounds = select_candidates(candidates, seed)
    source_fingerprint = hashlib.sha256(index_path.read_bytes()).hexdigest()
    experiment_id = hashlib.sha256(
        f"{SCHEMA_VERSION}:{seed}:{source_fingerprint}".encode()
    ).hexdigest()[:16]
    public_rounds = []
    private_plots: dict[str, Any] = {}
    output.mkdir(parents=True, exist_ok=True)
    for round_index, selected in enumerate(rounds, 1):
        public_plots = []
        for plot_index, row in enumerate(selected, 1):
            plot_id = f"R{round_index:02d}-P{plot_index:02d}"
            image_path = output / "plots" / f"{plot_id}.png"
            _plot_surface(row, image_path)
            report = _candidate_report(Path(row["source_path"]).parent)
            public_plots.append(
                {"plot_id": plot_id, "image": f"/plot/{plot_id}.png"}
            )
            private_plots[plot_id] = {
                "candidate_id": row["id"],
                "surface_score": float(row["responses"]["surface_score"]),
                "response_sha256": row["response_sha256"],
                "source_path": row["source_path"],
                "candidate_report": str(report) if report else None,
                "coverage_deg": float(row["coverage_deg"]),
                "mouth_mm": float(row["mouth_mm"]),
                "role": row.get("role"),
                "provenance": row.get("provenance"),
            }
        public_rounds.append({"round": round_index, "plots": public_plots})
    public = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "round_count": ROUND_COUNT,
        "plots_per_round": PLOTS_PER_ROUND,
        "rounds": public_rounds,
    }
    private = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "seed": seed,
        "source_index": str(index_path),
        "source_index_sha256": source_fingerprint,
        "sampling": {
            "rounds_1_through_10": (
                "one unique response from each current-surface-score decile per round"
            ),
            "rounds_11_through_20": (
                "ten nearest unused scores around successive 5th-through-95th "
                "surface-score quantiles"
            ),
        },
        "plots": private_plots,
    }
    _atomic_json(output / "experiment.json", public)
    _atomic_json(output / "private_manifest.json", private)
    (output / "index.html").write_text(WIDGET_HTML)


class ExperimentHandler(BaseHTTPRequestHandler):
    root: Path

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/index.html"):
            self._file(self.root / "index.html", "text/html; charset=utf-8")
        elif path == "/api/experiment":
            self._file(self.root / "experiment.json", "application/json")
        elif path == "/api/state":
            public = json.loads((self.root / "experiment.json").read_text())
            state_path = self.root / "rankings.json"
            state = (
                json.loads(state_path.read_text())
                if state_path.exists()
                else _initial_state(public)
            )
            self._json(state)
        elif path == "/final-report":
            self._file(self.root / "final_report.html", "text/html; charset=utf-8")
        elif path.startswith("/plot/") and PLOT_ID.fullmatch(Path(path).stem):
            self._file(self.root / "plots" / Path(path).name, "image/png")
        elif path.startswith("/candidate-report/"):
            plot_id = path.rsplit("/", 1)[-1]
            state_path = self.root / "rankings.json"
            if not state_path.exists() or not json.loads(state_path.read_text()).get(
                "complete"
            ):
                self.send_error(HTTPStatus.FORBIDDEN, "experiment is still blinded")
                return
            private = json.loads((self.root / "private_manifest.json").read_text())
            report_path = private["plots"].get(plot_id, {}).get("candidate_report")
            self._file(
                Path(report_path) if report_path else Path("/nonexistent"),
                "text/html; charset=utf-8",
            )
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/state":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("request is too large")
            candidate = json.loads(self.rfile.read(length))
            public = json.loads((self.root / "experiment.json").read_text())
            state_path = self.root / "rankings.json"
            previous = (
                json.loads(state_path.read_text()) if state_path.exists() else None
            )
            state = validate_state(candidate, public, previous)
            _atomic_json(state_path, state)
            if state["complete"]:
                private = json.loads((self.root / "private_manifest.json").read_text())
                build_report(self.root, state, private)
            self._json(state)
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format_string % args}")


def serve(output: Path, host: str, port: int) -> None:
    required = ("index.html", "experiment.json", "private_manifest.json")
    for name in required:
        if not (output / name).is_file():
            raise FileNotFoundError(output / name)
    handler = type("BoundExperimentHandler", (ExperimentHandler,), {"root": output})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Surface-ranking experiment: http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("index", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("--seed", type=int, default=DEFAULT_SEED)
    server = subparsers.add_parser("serve")
    server.add_argument("output", type=Path)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    report = subparsers.add_parser("report")
    report.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "build":
        build_experiment(args.index, args.output, args.seed)
    elif args.command == "serve":
        serve(args.output, args.host, args.port)
    else:
        state = json.loads((args.output / "rankings.json").read_text())
        private = json.loads((args.output / "private_manifest.json").read_text())
        print(build_report(args.output, state, private))


WIDGET_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blinded coverage-surface ranking</title>
<style>
:root{--ink:#172033;--muted:#64748b;--line:#cbd5e1;--paper:#f1f5f9;
--accent:#0f766e;--danger:#b91c1c} *{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(248,250,252,.96);
border-bottom:1px solid var(--line);padding:14px 24px;backdrop-filter:blur(8px)}
header>div,main{max-width:1180px;margin:auto} h1{font-size:21px;margin:0 0 3px}
.subhead,.status{color:var(--muted)} main{padding:22px}
.toolbar{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:16px}
button{border:1px solid var(--line);border-radius:8px;padding:9px 13px;background:white;
font:inherit;cursor:pointer} button.primary{background:var(--accent);border-color:var(--accent);
color:white;font-weight:650} button:disabled{opacity:.45;cursor:not-allowed}
.cards{display:grid;gap:14px}.card{display:grid;grid-template-columns:48px minmax(0,1fr) 300px;
gap:14px;align-items:start;background:white;border:1px solid var(--line);border-radius:12px;
padding:12px;box-shadow:0 1px 2px #0f172a10}.card.dragging{opacity:.35}
.rank{font-size:22px;font-weight:750;text-align:center;padding-top:8px}.rank small{display:block;
font-size:11px;color:var(--muted);font-weight:500}.plot-id{font-size:12px;color:var(--muted);
margin-bottom:5px}.card img{display:block;width:100%;height:auto;border:1px solid #e2e8f0;
border-radius:6px}.note label{display:block;font-size:12px;font-weight:700;margin-bottom:5px}
textarea{display:block;width:100%;min-height:118px;resize:vertical;border:1px solid var(--line);
border-radius:7px;padding:9px;font:inherit}.move{display:flex;gap:6px;margin-top:8px}
.save{font-size:12px;color:var(--muted)} .locked{color:var(--accent);font-weight:700}
.error{color:var(--danger)} .complete{background:white;border:1px solid var(--line);
border-radius:12px;padding:28px;text-align:center}
@media(max-width:850px){.card{grid-template-columns:40px minmax(0,1fr)}.note{grid-column:2}}
</style></head><body>
<header><div><h1>Blinded coverage-surface ranking</h1>
<div class="subhead">Drag into best-to-worst order. Plot notes are optional and will appear in the final report.</div>
</div></header><main><div id="app">Loading…</div></main>
<script>
let experiment, state, currentRound=1, saveTimer, dragged=null;
const app=document.querySelector("#app");
const esc=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
async function load(){
  [experiment,state]=await Promise.all([
    fetch("/api/experiment").then(r=>r.json()),fetch("/api/state").then(r=>r.json())
  ]);
  currentRound=[...Array(experiment.round_count)].map((_,i)=>i+1)
    .find(n=>!state.locked_rounds.includes(n))||experiment.round_count;
  render();
}
function plotsFor(round){
  const byId=Object.fromEntries(experiment.rounds[round-1].plots.map(p=>[p.plot_id,p]));
  return state.orders[String(round)].map(id=>byId[id]);
}
function render(){
  if(state.complete){
    app.innerHTML=`<div class="complete"><h2>All rankings are locked</h2>
      <p>Your ordering and per-plot notes are recorded.</p>
      <p><a href="/final-report" target="_blank">Open the unblinded comparison report</a></p></div>`;
    return;
  }
  const locked=state.locked_rounds.includes(currentRound);
  const cards=plotsFor(currentRound).map((plot,index)=>`<article class="card"
    draggable="${!locked}" data-id="${plot.plot_id}">
    <div class="rank">${index+1}<small>${index===0?"BEST":index===9?"WORST":""}</small></div>
    <div><div class="plot-id">${esc(plot.plot_id)}</div><img src="${plot.image}"
      alt="Blinded coverage surface ${esc(plot.plot_id)}" draggable="false"></div>
    <div class="note"><label for="note-${plot.plot_id}">Notes for this plot</label>
      <textarea id="note-${plot.plot_id}" data-note="${plot.plot_id}" maxlength="5000"
      placeholder="Optional observations…" ${locked?"disabled":""}>${esc(state.notes[plot.plot_id]||"")}</textarea>
      <div class="move"><button data-up="${plot.plot_id}" ${locked||index===0?"disabled":""}>↑ Up</button>
      <button data-down="${plot.plot_id}" ${locked||index===9?"disabled":""}>↓ Down</button></div></div>
    </article>`).join("");
  app.innerHTML=`<div class="toolbar"><div><strong>Round ${currentRound} of ${experiment.round_count}</strong>
    <span class="status"> · ${state.locked_rounds.length} locked</span><div id="save" class="save">Saved</div></div>
    <div><button id="previous" ${currentRound===1?"disabled":""}>Previous</button>
    <button id="next" ${currentRound===experiment.round_count?"disabled":""}>Next</button>
    <button id="lock" class="primary" ${locked?"disabled":""}>${locked?"Round locked":"Lock this ranking"}</button></div></div>
    <div class="cards">${cards}</div>`;
  bind();
}
function bind(){
  document.querySelector("#previous").onclick=()=>{currentRound--;render()};
  document.querySelector("#next").onclick=()=>{currentRound++;render()};
  document.querySelector("#lock").onclick=lockRound;
  document.querySelectorAll("[data-note]").forEach(field=>{
    field.oninput=()=>{state.notes[field.dataset.note]=field.value;scheduleSave()};
  });
  document.querySelectorAll("[data-up]").forEach(button=>button.onclick=()=>move(button.dataset.up,-1));
  document.querySelectorAll("[data-down]").forEach(button=>button.onclick=()=>move(button.dataset.down,1));
  document.querySelectorAll(".card[draggable=true]").forEach(card=>{
    card.ondragstart=()=>{dragged=card.dataset.id;card.classList.add("dragging")};
    card.ondragend=()=>{dragged=null;card.classList.remove("dragging")};
    card.ondragover=event=>event.preventDefault();
    card.ondrop=event=>{event.preventDefault();if(dragged&&dragged!==card.dataset.id){
      const order=state.orders[String(currentRound)],from=order.indexOf(dragged),to=order.indexOf(card.dataset.id);
      order.splice(to,0,order.splice(from,1)[0]);render();scheduleSave();
    }};
  });
}
function move(id,delta){
  const order=state.orders[String(currentRound)],from=order.indexOf(id),to=from+delta;
  if(to<0||to>=order.length)return;[order[from],order[to]]=[order[to],order[from]];
  render();scheduleSave();
}
function scheduleSave(){
  clearTimeout(saveTimer);const label=document.querySelector("#save");
  if(label)label.textContent="Unsaved changes…";
  saveTimer=setTimeout(save,450);
}
async function save(){
  clearTimeout(saveTimer);
  const response=await fetch("/api/state",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(state)});
  const result=await response.json();
  if(!response.ok){const label=document.querySelector("#save");if(label){label.textContent=result.error;
    label.classList.add("error")}throw new Error(result.error)}
  state=result;const label=document.querySelector("#save");if(label)label.textContent="Saved";
}
async function lockRound(){
  if(!confirm("Lock this best-to-worst order and its notes? It cannot be edited afterward."))return;
  if(!state.locked_rounds.includes(currentRound))state.locked_rounds.push(currentRound);
  await save();
  currentRound=[...Array(experiment.round_count)].map((_,i)=>i+1)
    .find(n=>!state.locked_rounds.includes(n))||experiment.round_count;
  render();
}
load().catch(error=>{app.innerHTML=`<p class="error">${esc(error)}</p>`});
</script></body></html>
"""


if __name__ == "__main__":
    main()
