---
name: developing-in-shadow
description: "Shared shadow-development pattern: mode-state ladders, non-blocking telemetry, scoring, gate checks, and isolation audits."
covers_families: []
distinctive_strings:
  - "developing-in-shadow"
  - "cisternal shadow check"
  - "cisternal shadow score"
  - "shadow-development"
---

# developing-in-shadow

The shadow-development pattern allows candidate logic or experimental subagents to run alongside production or test workflows, recording what they would have done without actuating or causing side effects, calibrating empirical accuracy against ground truth, and enforcing pre-registered promotion gates before cutover.

## When to Use

Use when a new gate, classifier, mapper or subagent should run beside the live path before it is trusted: authoring a `.praxia/mode_state/<feature>.toml`, emitting shadow verdicts, scoring them against labels with `cisternal shadow score`, or checking a promotion gate with `cisternal shadow check`.

## Stage Ladder

Every candidate feature progresses through a 4-stage lifecycle:
1. `off`: Feature is inactive.
2. `shadow`: Candidate runs alongside live logic. All writes are strictly confined to shadow logs; candidate verdicts never modify actor output or live state.
3. `advisory`: Candidate verdicts are presented to human actors or higher-level agents for guidance, but not enforced (non-blocking). Promotion to advisory requires passing a pre-registered promotion gate.
4. `enforce`: Feature acts as an authoritative, blocking gate or live implementation.

## 7-Step Implementation Lifecycle

### Step 1: Pre-register Mode-State TOML

Before running candidate code, author and version-control a mode-state file under `.praxia/mode_state/<feature>.toml` (or `.cisternal/mode_state/<feature>.toml`):

```toml
[feature]
name = "bearings_charter_mapper"
description = "Maps experiment sidecars to research charter purposes"
version = "0.1.0"

[ladder]
current_stage = "shadow"

[shadow]
traffic_fraction = 1.0
writes_isolated = true
writes_isolated_enforced_by = "tests/test_isolation.py::test_charter_mapper_isolation"

[scoring]
positive_label = true

[promotion]
target_stage = "advisory"
min_verdicts = 30
min_labels = 15
allowed_label_sources = ["frozen_gold", "owner_confirmed", "at_work"]
min_precision = 0.85
min_precision_lower_bound = 0.70
min_recall = 0.80
min_recall_lower_bound = 0.65
max_fp_rate = 0.05
isolation_violations_max = 0
threshold_basis = "pre-registered calibration based on domain requirements"
```

### Step 2: Initialize Telemetry Pipeline

At application or test startup, initialize telemetry once:

```python
import cisternal

cisternal.init()
```

If uninitialized, shadow emit functions preserve library isolation and return `False` without raising or spawning background threads.

### Step 3: Emit Candidate Verdicts (non-blocking telemetry)

In the candidate evaluation path, emit non-blocking verdicts:

```python
import cisternal.shadow

accepted = cisternal.shadow.emit_verdict(
    feature="bearings_charter_mapper",
    subject_key=f"sidecar:{sidecar_id}",
    verdict={"decision": "pass", "confidence": 0.92},
    stage="shadow",
    feature_version="0.1.0",
    inputs_sha256=input_payload_hash,
)
```

### Step 4: Capture Ground Truth Labels

Attach verified ground truth using structured provenance sources (`frozen_gold > owner_confirmed > at_work > retrospective`):

```python
cisternal.shadow.emit_label(
    feature="bearings_charter_mapper",
    subject_key=f"sidecar:{sidecar_id}",
    label=True,
    label_source="frozen_gold",
    labeller="reviewer_id",
)
```

### Step 5: Score Evaluation with Wilson Intervals

Calculate confusion metrics and Wilson confidence intervals:

```bash
cisternal shadow score bearings_charter_mapper --records-dir /path/to/logs
```

The scorer joins strictly on `subject_key`, resolves multiple verdicts by latest timestamp, prioritizes label provenance, and refuses on zero labels (exit code 2). Confirm that the Wilson CI lower bound strictly exceeds the empirical base rate.

### Step 6: Verify Actor Isolation

Verify that the shadow arm does not alter live outputs or leak side effects outside its log directory:

```python
from cisternal.shadow import prove_isolation

def test_charter_mapper_isolation(tmp_path):
    live_dir = tmp_path / "live"
    shadow_log = tmp_path / "logs"

    res = prove_isolation(
        actor_live_fn=run_baseline_mapper,
        actor_shadow_fn=run_shadow_mapper,
        live_roots=[live_dir],
        shadow_log_dir=shadow_log,
        feature="bearings_charter_mapper",
        enforced_by="tests/test_isolation.py::test_charter_mapper_isolation",
    )
    assert res.passed
```

Pass `feature=` so the call emits a `shadow.isolation` event (it emits nothing when `feature` is empty, and also when telemetry is uninitialized). `cisternal shadow check` blocks promotion unless it finds a passing isolation event, `writes_isolated = true` and a named enforcer.

### Step 7: Check Promotion Readiness

Run the read-only gate evaluation:

```bash
cisternal shadow check bearings_charter_mapper --records-dir /path/to/logs
```

- Exit 0: Promotion permitted (`promotion_permitted = true`, `blocking_reasons = []`).
- Exit 1: Promotion blocked (`blocking_reasons` lists all deficits).
- Exit 2: Refusal (0 matching telemetry).
- Exit 3: Configuration error (malformed TOML or unresolvable path).

Note: `cisternal shadow check` is strictly read-only. It never mutates mode-state files or git; advancing stages requires an explicit commit.

## Worked Example: Bearings AC-9 (bathos spec 261104) — illustrative

The numbers below are illustrative, not results: Bearings AC-9 has not been run through this pattern yet. They are chosen so every gate in the Step 1 mode-state passes.

In Bathos Bearings (spec 261104), a candidate reader maps experiment sidecars (`.bth.toml`) to research charter purposes:
1. Mode-state pre-registered at `.praxia/mode_state/bearings_charter_mapper.toml` with `target_stage = "advisory"`.
2. Telemetry records are written during batch sidecar evaluation with `emit_verdict`.
3. Ground truth is labeled across 60 frozen reference sidecars (`frozen_gold`), 30 positive and 30 negative (base rate 0.50).
4. `cisternal shadow score bearings_charter_mapper` would report TP=27, FP=1, FN=3, TN=29: precision 0.964 [Wilson 95% CI: 0.823 .. 0.994], recall 0.900 [0.744 .. 0.965], false positive rate 0.033. The precision lower bound (0.823) clears both `min_precision_lower_bound = 0.70` and the base rate.
5. `prove_isolation(..., feature="bearings_charter_mapper")` passes and emits a passing `shadow.isolation` event. The gate requires this evidence: with no passing event, `check` blocks with `no_isolation_evidence`.
6. Only when all of the above hold does `cisternal shadow check bearings_charter_mapper` exit 0, permitting the owner to promote `current_stage` to `"advisory"` by an explicit commit. A smaller sample fails closed: for example 18/20 gives a precision lower bound of 0.699, below the 0.70 gate, and `check` exits 1.
