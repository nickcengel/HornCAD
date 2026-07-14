# HornCAD Python Setup

HornCAD uses Python 3.13 in a project-local virtual environment. Do not install
HornCAD dependencies into macOS system Python.

## Python Version

Use Homebrew Python 3.13:

```sh
brew install python@3.13
```

This should provide:

```sh
/opt/homebrew/bin/python3.13
```

## Bootstrap The Project

From the repo root:

```sh
make bootstrap
```

This recreates `.venv` from `/opt/homebrew/bin/python3.13`, upgrades pip inside
that venv, and installs HornCAD with dev dependencies.

Run tests with:

```sh
make test
```

Inspect what Python the project is using with:

```sh
make python-info
```

## If Python Gets Weird

Delete and rebuild only the project venv:

```sh
make clean-venv
make bootstrap
```

Do not use `sudo pip`, do not install dependencies into `/usr/bin/python3`, and
do not edit shell PATH just to work on this project.
