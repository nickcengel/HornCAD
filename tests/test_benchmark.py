import csv

from horncad.benchmark import run_benchmark
from horncad.config import dump_config
from tests.helpers import small_project_config


def test_run_benchmark_writes_scorecard_csv(tmp_path):
    project = tmp_path / "project.yaml"
    project.write_text(dump_config(small_project_config()), encoding="utf-8")
    output = tmp_path / "scorecard.csv"

    rows = run_benchmark([project], output=output, workers=1)

    assert len(rows) == 1
    assert rows[0]["project"] == str(project)
    assert float(rows[0]["objective_score"]) >= 0.0
    assert float(rows[0]["area_rms_log"]) >= 0.0
    assert int(rows[0]["candidates"]) > 0

    written = list(csv.DictReader(output.open(encoding="utf-8")))
    assert written[0]["project"] == str(project)
    assert "objective_area_rms_log" in written[0]
    assert "objective_K_drift" in written[0]
