# Skill trigger harness: positive/negative controls (debt #1271)

`trigger_harness_controls.py` checks that skill-creator's trigger-evaluation
harness (`scripts/run_eval.py` in the installed skill-creator skill) can
actually register a trigger, before any of its numbers are trusted.
Pre-registration: `trigger_harness_controls.bth.toml`.

## Verdict (2026-09-30): the harness works — when `claude -p` can reach the API

Run `9835961b-3966-45df-9257-4920ad14ed9b` (bathos, unsandboxed; recorded
outcome **pass**), harness sha256 `43e3b8f8…57f`. An identical
earlier run (`60d1363b…`) gave the same 3/3 and 0/3 but recorded
`outcome=unknown` because the script did not yet write `$BTH_RESULTS_PATH`.

| control | query | trigger rate | criterion | result |
|---|---|---|---|---|
| positive | "Please handle this zebrafrob for me." | 3/3 = 1.00 | ≥ 0.67 | pass |
| negative | "What is 2+2?" | 0/3 = 0.00 | ≤ 0.33 | pass |

Raw `claude -p` probe exit 0; 0 harness exceptions.

An earlier run (`5a42e96e…`) executed inside the Claude Code Bash sandbox:
there `claude -p` cannot reach the API and hangs until timeout, so every query
scored 0. That run measured the sandbox, not the harness, and is superseded.

## What this means for the July result

`run_eval.py` runs `claude -p` with `stderr=DEVNULL` and returns
`triggered=False` on **any** failure (crash, auth, network, timeout, no
stream). A harness that cannot run is therefore indistinguishable from a
description that never triggers. The 2026-07-23 optimization run reported
0/5 on every should-trigger query (the 0.0 on the 5 should-not-trigger
queries is the correct answer, not a symptom). Given the failure mode above,
that result cannot be read as evidence about the `developing-cisternal-tools`
description. Do not rewrite the description based on it.

## Rerun

Must run **outside** the Bash sandbox (nested `claude -p` needs API egress):

```bash
bth run --project-slug cisternal -- uv run --no-sync python3 scripts/diag/trigger_harness_controls.py
# optional: --harness-dir <skill-creator dir> --runs 3 --timeout 90
```

Run this control first whenever the description optimizer reports uniform
zeros, and run the optimizer itself unsandboxed.
