# macOS Apple Silicon setup

This is a compact environment handoff for a clean Apple Silicon Mac. Keep the
toolchain native arm64; do not mix Rosetta Python or Homebrew packages.

## Python environment

Install Xcode command-line tools, Homebrew, and the exact Python series required
by `pyproject.toml`:

```bash
xcode-select --install
brew install python@3.13
git clone https://github.com/nickcengel/HornCAD.git
cd HornCAD
make bootstrap
```

`make bootstrap` recreates `.venv`, updates packaging tools, and installs
HornCAD editable with its Python dependencies. Confirm the interpreter is arm64
Python 3.13:

```bash
.venv/bin/python --version
file -L .venv/bin/python
```

## Native NumCalc

HornCAD's production free-air BEM path uses the NumCalc source distributed with
Mesh2HRTF. Its simple Makefile builds successfully with Apple's native `g++`
alias (`clang++`); no separate GCC or OpenMP runtime is required.

```bash
git clone https://github.com/Any2HRTF/Mesh2HRTF.git /private/tmp/Mesh2HRTF
make -C /private/tmp/Mesh2HRTF/mesh2hrtf/NumCalc/src
mkdir -p build/numcalc
cp /private/tmp/Mesh2HRTF/mesh2hrtf/NumCalc/bin/NumCalc build/numcalc/NumCalc
chmod +x build/numcalc/NumCalc
file build/numcalc/NumCalc
```

The final `file` output should identify a Mach-O arm64 executable. HornCAD
automatically checks `build/numcalc/NumCalc`; commands also accept an explicit
`--binary` or `--numcalc` path.

## Smoke checks

First check Python imports:

```bash
.venv/bin/python -c "import gmsh, numpy, scipy, trimesh, yaml"
```

Then exercise HornCAD mesh generation and NumCalc's memory estimator without
running an acoustic solve:

```bash
.venv/bin/python app/tools/run_numcalc_sweep.py \
  examples/osse-400x280-reference/project.yaml \
  --numcalc build/numcalc/NumCalc \
  --output-dir /private/tmp/horncad-bem-smoke \
  --start-hz 500 --stop-hz 501 --points 1 \
  --elements-per-wavelength 4 --angles 9 \
  --maximum-workers 1 --dry-run
```

For repository validation, install Node if needed and run `make validate`.

## Practical notes

- Run commands from the repository root and use `.venv/bin/python` explicitly.
- A MacBook Air is fanless. Start real BEM work with one or two workers and
  increase only after checking memory use and sustained thermals.
- BEM sweeps and candidate searches are resumable. Reuse the same output
  directory; do not delete state or completed frequency directories.
- The solver suite places Matplotlib and font caches under the repository's
  `.cache` directory to avoid macOS cache-permission failures.
