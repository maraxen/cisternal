# minimal_emitter

Example third-party package registering a `cisterna.emitters` entry point.

## Install

From the cisterna repo root (with `uv sync` already run):

```bash
uv pip install -e examples/minimal_emitter
```

## Entry point

`pyproject.toml` declares:

```toml
[project.entry-points."cisterna.emitters"]
minimal = "minimal_emitter:factory"
```

The factory must be callable as `factory(**kwargs) -> Emitter`.

## Verify

```bash
uv run python -c "from cisterna.export.registry import list_emitter_surfaces; print(list_emitter_surfaces())"
```

Expect `minimal` alongside the four built-in surfaces when this package is installed.
