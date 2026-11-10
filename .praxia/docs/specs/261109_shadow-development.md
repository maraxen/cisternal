---
title: "Specification: Shared shadow-development pattern and cisternal.shadow module"
description: "Shared shadow-development pattern providing telemetry events, scoring, stage-gated promotion checks, actor isolation verification, and adoption skill in cisternal."
task_id: 261109_cisternal-shadow-development
date: '261109'
status: draft
---

# Specification: Shared shadow-development pattern and cisternal.shadow module

## 1. Goal

Establish a shared, standard shadow-development pattern across the Praxia tool family, implemented in `cisternal` as:
1. Standard telemetry events: `shadow.verdict`, `shadow.label`, and `shadow.isolation` emitted through cisternal's existing JSONL telemetry pipeline.
2. Scoring engine and CLI: `cisternal shadow score <feature>` performing structured joins across verdict and label records by `subject_key`, computing confusion metrics, precision, and recall alongside base rates with Wilson score confidence intervals, refusing on zero labels.
3. Mode-state TOML configuration and gate evaluator CLI: `cisternal shadow check` computing `promotion_permitted` and `blocking_reasons` across a four-stage ladder (`off -> shadow -> advisory -> enforce`) without mutating configuration.
4. Actor isolation harness: a generalized pytest helper `prove_isolation` verifying that an actor's outputs remain byte-identical with shadow enabled vs disabled, and that all shadow-arm side effects are strictly confined to its log.
5. Agent skill: `developing-in-shadow` at `.praxia/skills/developing-in-shadow/SKILL.md` in the cisternal plugin providing end-to-end guidance and a worked Bearings AC-9 example.

### 1.1 Fixed Owner Decisions (Non-negotiable)

- **Repo ownership & Adoption**: The spec, module code, and skill live in `cisternal`. Bearings AC-9 (bathos spec 261104) is the first adopter; bathos, maraxiom, and praxia will migrate later, outside this PR.
- **Stage ladder**: `off -> shadow -> advisory -> enforce`. `advisory` means the feature verdict is presented to the actor but not enforced (non-blocking).
- **Label provenance**: Every label carries a provenance source: `at_work | owner_confirmed | retrospective | frozen_gold`.
- **Promotion check immutability**: `cisternal shadow check` computes `promotion_permitted` and `blocking_reasons`. Nothing ever advances or mutates a stage automatically; promotion requires explicit owner action.
- **Derived-data locations hierarchy**: Resolution strictly follows:
  `explicit CLI argument / API parameter > environment variable (none/empty string disables) > [tool.cisternal] in pyproject.toml > ${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml > off`.
  No default path in library code; fail loudly on malformed configuration; report which layer decided. (See §3.7 for explicit keys, environment variables, and diagnostic reporting contracts).

---

## 2. Problem & Evidence

### 2.1 Background: Four Divergent Implementations

Shadow execution (running a candidate feature in production or alongside live workflows, recording what it would have done, never allowing it to actuate, and calibrating accuracy against ground truth before promotion) has been implemented four separate times across the tool family:

| Subsystem | Verdict Storage | Label Mechanism | Promotion Mechanism | Isolation Mechanism |
|---|---|---|---|---|
| **praxia dispatch / mode-state** | `shadow_pair_id` minted via `crates/praxia-dispatch/src/envelope.rs:62`; stamped on `ExecutionReport` (`record.rs:79-89`); `.praxia/mode_state/*.toml` | Frozen pre-registered gold holdouts; disagreement sampling (D3f in `specs/261023_d3f-fft-shadow.md`) | `check-mode-state` in `scripts/eval/shadow_exec_driver.py:1398` enforces thresholds | `prove_isolation` in `scripts/eval/shadow_exec_driver.py:519` with separate clone and mtime/sha snapshot diff |
| **maraxiom reader_text** | Per-build log `<recipe>/_reader_text/<build_id>.jsonl` with `classify: null` (`src/maraxiom/reader_text.py:954`) | Retrospective human classifications in `classifications.jsonl` (`reader_text.py:1001`; `cli.py:2418`); PMC OA legend corpus | Pre-registered C1/C2 bounds in `specs/261026_review-reader-layer.md §6`; owner decision OD-1 with `REFUSING_RULES` / `SHADOW_SUBRULES` (`reader_text.py:307-316`) | Build output is verified unchanged |
| **bathos blast-radius** | `shadow_verdict` column in `blast_radius_ledger` (`src/bathos/blast_radius.py:56, 76, 101, 1057, 1109`); `shadow_trigger` entity (`:1412`) | None (unmeasured trigger precision) | None implemented | `to_state` set by caller, never by shadow verdict; shadow trigger never calls flag or propagate |
| **cisternal telemetry** | `ShadowExporter` test spy (`src/cisternal/telemetry/exporter.py:148-162`); `tests/shadow/harness.py` | N/A | Parity must pass before cutover | N/A |

### 2.2 Historical Gaps and Audit Failure Classes

Prior implementations suffered from specific structural defects that cisternal's shared architecture must prevent:

1. **Incomplete Joins via Fragile Text-Search (Praxia T3 Failure)**:
   - *Evidence*: In `audits/260925_t3-live-shadow-pair.md`, the joiner returned `complete: false, rc=2` because `scripts/analysis/shadow_pair_join.py` text-searched prompt messages and raw transcript files instead of reading structured correlation keys from event streams.
   - *Design Response*: Cisternal joins strictly on structured `subject_key` extracted from validated event records, never parsing unstructured log text.

2. **Driver Spawning & Flag-Forwarding Failures (Praxia T22 Failure)**:
   - *Evidence*: In `audits/260926_t22-live-shadow-execution.md`, three consecutive shadow runs failed: (a) relative paths failed when subprocesses executed in `S/live` cwd; (b) CLI flags (`--shadow-arm`, `--shadow-cmd`, `--surface`) were parsed by `main()` but silently omitted when invoking `run()`; (c) V6 leak detection in `.praxia/leak.txt` failed isolation.
   - *Design Response*: All paths resolved to absolute before spawning; strong CLI parameter propagation; enforced isolation verification with leak detection.

3. **Inappropriate Baseline Comparison (Praxia Fast-and-Frugal Tree Defect)**:
   - *Evidence*: In `skills/developing-fast-frugal-trees/SKILL.md:79`, a triage gate (`non_task`) fired 19 times, was correct only twice (precision 0.10 against a base rate of 0.56), and degraded overall performance.
   - *Design Response*: `cisternal shadow score` reports precision and recall explicitly alongside the empirical base rate.

4. **Sample Size and Under-coverage in Calibration (Maraxiom C1/C2 Failure)**:
   - *Evidence*: In `audits/260926_reader-text-calibration-results.md`, calibration failed on C1 recall (lower bound 0.29 on R1) and C2 false-positive rate (10 of 150 clean legends flagged on R7).
   - *Design Response*: Scorer computes exact binomial confidence intervals using the Wilson score interval and enforces minimum sample thresholds before computing promotion gates.

---

## 3. Design Specification

### 3.1 Event Schemas & Telemetry Pipeline Integration

All shadow events are serialized as standard JSON records emitted through cisternal's existing JSONL telemetry pipeline (`cisternal.emit_event` and `cisternal.shadow.emit_*`).

#### Telemetry Record Envelope Mapping
In cisternal (`src/cisternal/telemetry/record.py:8-43` and `src/cisternal/telemetry/exporter.py:103-120`), telemetry records are structured instances of `Record`:
- `name: str` — the event identifier (`"shadow.verdict"`, `"shadow.label"`, `"shadow.isolation"`).
- `ts: float` — UTC timestamp in epoch seconds (`time.time()`).
- `run_uuid: str` — unique identifier of the active execution session.
- `fields: dict[str, Any]` — dictionary containing all domain-specific payload attributes.

When serialized to JSONL via `JsonlExporter`, records take the shape:
```json
{"name": "shadow.verdict", "ts": 1731168000.123, "run_uuid": "...", "fields": {"feature": "...", "subject_key": "...", ...}}
```

#### Pipeline Initialization & Return Status Invariant
`cisternal.init(...)` must be called at application or worker startup to initialize the global telemetry pipeline. If the pipeline is uninitialized, calls to `cisternal.shadow.emit_verdict(...)` and `cisternal.shadow.emit_label(...)` do NOT auto-initialize background worker threads or file handlers (preserving library isolation in uninstrumented test suites).
Instead, `emit_verdict` and `emit_label` return a boolean `bool` status:
- `True` if the event was accepted and enqueued by an active telemetry pipeline.
- `False` if dropped due to an uninitialized pipeline or active log level filtering.

#### Transparent Reader Unwrapping
Downstream readers, including `cisternal shadow score` and `cisternal shadow check`, must unwrap records transparently:
- Domain fields are extracted via `record.get("fields", record)`. This transparently supports both native cisternal `Record` envelopes (`record["fields"]["subject_key"]`) and standalone flat JSON records (`record["subject_key"]`).
- Timestamps are normalized transparently, parsing either float epoch seconds (`1731168000.123`) or ISO 8601 strings (`"2026-11-09T16:00:00Z"`).

#### 3.1.1 `shadow.verdict` Event
Emitted by an instrumented feature when evaluating an input in shadow, advisory, or enforce mode.

| Envelope Key | Field in `fields` | Type | Description |
|---|---|---|---|
| `name` | — | `str` | Must be `"shadow.verdict"` |
| `ts` | — | `float` | UTC timestamp in epoch seconds (or ISO 8601 string on legacy ingest) |
| — | `feature` | `str` | Unique feature slug (e.g., `"bearings_charter_mapper"`, `"blast_radius_auto_clear"`) |
| — | `feature_version` | `str` | Content hash or version identifier of the feature logic |
| — | `subject_key` | `str` | Unique join key identifying the item evaluated (e.g., `"run:01a79c37"`, `"sha256:e3b0c442..."`). Recommended: `<entity_type>:<id>` |
| — | `stage` | `str` | Current operational stage: `"off"`, `"shadow"`, `"advisory"`, or `"enforce"` |
| — | `verdict` | `dict[str, Any]` \| `bool` \| `str` \| `int` | The candidate verdict payload (e.g., `{"decision": "pass", "confidence": 0.92}`) |
| — | `inputs_sha256` | `str` | SHA-256 hash of the exact input payload fed into the feature |

**Prediction Extraction Contract**:
When evaluating `verdict` for scoring and classification:
1. If `verdict` is a `dict`, candidate prediction is extracted by inspecting keys in priority order:
   - `verdict.get("prediction")`
   - `verdict.get("decision")`
   - `verdict.get("verdict")`
   - `verdict.get("value")`
   If none of these keys exist, the record is flagged as unmappable and counted under `invalid_records`.
2. If `verdict` is a primitive (`bool`, `str`, `int`), it is evaluated directly as the candidate prediction.

#### 3.1.2 `shadow.label` Event
Emitted when ground truth or human feedback is attached to an item.

| Envelope Key | Field in `fields` | Type | Description |
|---|---|---|---|
| `name` | — | `str` | Must be `"shadow.label"` |
| `ts` | — | `float` | UTC timestamp in epoch seconds |
| — | `feature` | `str` | Feature slug matching the corresponding `shadow.verdict` |
| — | `subject_key` | `str` | Unique join key matching the corresponding `shadow.verdict` |
| — | `label` | `Any` | Ground truth label value (e.g., `true`, `"pass"`, `"clean"`, `1`) |
| — | `label_source` | `str` | Provenance category: `"at_work"`, `"owner_confirmed"`, `"retrospective"`, or `"frozen_gold"` |
| — | `labeller` | `str` | Identifier of agent or user who authored the label |

#### 3.1.3 `shadow.isolation` Event
Emitted by `prove_isolation` or automated isolation harnesses upon completing an actor-isolation verification audit.

| Envelope Key | Field in `fields` | Type | Description |
|---|---|---|---|
| `name` | — | `str` | Must be `"shadow.isolation"` |
| `ts` | — | `float` | UTC timestamp in epoch seconds |
| — | `feature` | `str` | Feature slug under isolation test |
| — | `writes_isolated` | `bool` | `true` if live output was identical and all writes were confined to `shadow_log_dir`; `false` otherwise |
| — | `leaked_paths` | `list[str]` | List of file paths created, modified, or deleted outside allowed shadow directory (empty if passed) |
| — | `enforced_by` | `str` | Enforcer test symbol identifier (e.g., `"tests/shadow/test_isolation.py::test_feature_isolation"`) |

`cisternal shadow check` scans the telemetry store for `shadow.isolation` records matching `feature`. If any record has `writes_isolated == false` or `leaked_paths` non-empty, the check records `isolation_violation_detected` in `blocking_reasons`.

### 3.2 Scoring Engine & CLI (`cisternal shadow score`)

Command:
```bash
cisternal shadow score <feature> [--records-dir <path>] [--verdicts-file <path>] [--labels-file <path>] [--positive-label <val>] [--confidence <float>]
```

Behavior:
1. **Join Semantics & Stream Aggregation**:
   - Matches records on `subject_key` where `verdict.feature == label.feature == <feature>`.
   - **Multi-Process / Multi-File Aggregation**: When `--records-dir` (or the 5-layer resolved log directory, §3.7) is specified, streams and aggregates all matching `events.*.jsonl` (and `*.jsonl`) files in the directory. Targeted single-file overrides `--verdicts-file` and `--labels-file` allow scoring specific files directly.
   - **Latest-Timestamp Resolution**: If multiple verdicts exist for a single `subject_key`, the latest verdict by timestamp is selected.
   - **Provenance Precedence**: If multiple labels exist for a single `subject_key`, the label with highest provenance precedence is selected:
     `frozen_gold > owner_confirmed > at_work > retrospective` (with ties broken by latest timestamp).
2. **Prediction Extraction & Positive-Class Mapping**:
   - Extracts the candidate prediction from `verdict` per §3.1.1.
   - Resolves `positive_label` from `--positive-label <val>`, mode-state TOML `[scoring] positive_label`, or default `true` / `"pass"`.
   - Binary matching:
     - If `positive_label` is boolean (`isinstance(positive_label, bool)`):
       - If `val` is a boolean (`isinstance(val, bool)`): Positive if `val is positive_label`; otherwise Negative.
       - If `val` is numeric (`isinstance(val, (int, float))` and not `bool`): Positive if `bool(val) is positive_label`; otherwise Negative (e.g., `1` is `True`, `0` is `False`).
       - If `val` is a string (`isinstance(val, str)`): parse string case-insensitively:
         - If `positive_label is True`: Positive if `val.strip().lower() in ("true", "1", "yes", "pass", "clean")`; otherwise Negative.
         - If `positive_label is False`: Positive if `val.strip().lower() in ("false", "0", "no", "fail", "drifted")`; otherwise Negative.
       - Any other type or unmappable string: counted under `invalid_records` and omitted from confusion metrics.
     - If `positive_label` is string/primitive:
       - If `val` is a boolean: normalized to `"true"` or `"false"` and compared case-insensitively.
       - Value is Positive if `str(val).strip().lower() == str(positive_label).strip().lower()`; otherwise Negative.
   - A subject is $TP$ if both prediction and label are Positive; $FP$ if prediction is Positive and label is Negative; $FN$ if prediction is Negative and label is Positive; $TN$ if both are Negative.
   - Unmappable verdicts or labels are counted under `invalid_records` and omitted from confusion metrics.
3. **Refusal on Zero Labels**:
   - If zero labels match the feature, the scorer refuses to calculate dummy metrics (such as 0.0 or 1.0).
   - It exits with exit code 2 and outputs:
     `REFUSAL: feature '<feature>' has 0 matching labels. Scoring requires at least 1 labeled subject.`
4. **Zero-Denominator Handling**:
   - If $TP + FP = 0$ (the candidate feature made zero positive predictions across all labeled subjects): Precision is mathematically undefined; reported as `null` / `"n/a (no positive predictions)"`, with Wilson CI bounds `null`.
   - If $TP + FN = 0$ (the labeled dataset contains zero positive ground truth instances): Recall is mathematically undefined; reported as `null` / `"n/a (no positive labels)"`, with Wilson CI bounds `null`. Base rate is reported as $0.0$.
   - If $FP + TN = 0$ (the labeled dataset contains zero negative ground truth instances): False Positive Rate is mathematically undefined; reported as `null` / `"n/a (no negative labels)"`.
   - No zero-denominator condition raises `ZeroDivisionError`.
5. **Metrics Reported**:
   - **Confusion Matrix**: True Positives ($TP$), False Positives ($FP$), True Negatives ($TN$), False Negatives ($FN$), Unlabelled Verdicts ($N_{unlabelled}$), Invalid Records ($N_{invalid}$).
   - **Base Rate**: Empirical positive class prevalence in the labeled population $\frac{TP + FN}{N_{labeled}}$.
   - **Precision**: $\frac{TP}{TP + FP}$ alongside Wilson score confidence interval bounds at the specified confidence level (default 95%, configurable via `--confidence`).
   - **Recall**: $\frac{TP}{TP + FN}$ alongside Wilson score confidence interval bounds.
   - **Comparison against Base Rate**: Flag indicating whether the precision lower bound strictly exceeds empirical base rate.
6. **Wilson Score Confidence Interval Formula**:
   Computed analytically via Python standard library `math` without external dependencies (`scipy` is not required):
   $$\tilde{p} = \frac{k + \frac{z^2}{2}}{n + z^2}, \quad w = \frac{z}{n + z^2}\sqrt{\frac{k(n-k)}{n} + \frac{z^2}{4}}$$
   $$\text{Lower Bound} = \max\left(0.0, \tilde{p} - w\right), \quad \text{Upper Bound} = \min\left(1.0, \tilde{p} + w\right)$$
   where $k$ is the numerator ($TP$), $n$ is the denominator ($TP + FP$ for precision, $TP + FN$ for recall), and $z$ is the standard normal quantile ($z \approx 1.95996$ for 95% confidence). Bounds are strictly contained in $[0, 1]$.

### 3.3 Mode-State Configuration & Evaluation (`cisternal shadow check`)

#### 3.3.1 Mode-State TOML Schema (`.praxia/mode_state/<feature>.toml` or `.cisternal/mode_state/<feature>.toml`)

```toml
[feature]
name = "example_shadow_feature"
description = "Description of candidate feature under shadow evaluation"
version = "0.1.0"

[ladder]
current_stage = "shadow" # "off" | "shadow" | "advisory" | "enforce"

[shadow]
traffic_fraction = 1.0
writes_isolated = true
writes_isolated_enforced_by = "tests/shadow/test_isolation.py::test_feature_isolation"

[scoring]
positive_label = true # or "pass", "clean", etc.

[promotion]
target_stage = "advisory" # or "enforce"
min_verdicts = 30
min_labels = 15
allowed_label_sources = ["frozen_gold", "owner_confirmed", "at_work"]
min_precision = 0.85
min_precision_lower_bound = 0.70
min_recall = 0.80
min_recall_lower_bound = 0.65
max_fp_rate = 0.05
isolation_violations_max = 0
threshold_basis = "pre-registered calibration based on domain requirement"
```

#### 3.3.2 Gate Evaluation Semantics and Exit Codes

Command:
```bash
cisternal shadow check <feature_or_path> [--records-dir <path>] [--json]
```

Behavior:
1. **Mode-State & Telemetry Resolution**:
   - Resolves mode-state TOML path via argument or 5-layer hierarchy (§3.7).
   - Resolves telemetry records directory via `--records-dir` or 5-layer hierarchy (§3.7).
   - Validates TOML schema; if malformed or missing required keys, exits with exit code 3.
2. **Enforcer Symbol Resolution (`writes_isolated_enforced_by`)**:
   - Format: `<relative_path_to_file>::<symbol_name>` (e.g., `tests/shadow/test_isolation.py::test_feature_isolation`).
   - Resolution: Resolved relative to the nearest git repository root via `importlib.util.spec_from_file_location`.
   - Secondary Fallback: If the file path does not exist on disk, attempts module import `<module_path>::<symbol_name>` via `importlib.import_module`.
   - If the enforcer symbol cannot be resolved or imported, records `enforcer_unimportable:<symbol>` and fails the isolation check.
3. **Non-Short-Circuiting Gate Evaluation**:
   Evaluates all gate conditions across the telemetry store, accumulating ALL failures into `blocking_reasons` without early return:
   - **Isolation Integrity**: Enforcer symbol must be importable, and the store must contain $\le \text{isolation\_violations\_max}$ violations (scans `shadow.isolation` events for `writes_isolated == false` or `leaked_paths` non-empty). If violations exist, records `isolation_violation_detected`.
   - **Sample Size Gates**: Total evaluated verdicts $\ge \text{min\_verdicts}$; total matching labels $\ge \text{min\_labels}$. If deficient, records `insufficient_verdicts:<actual>/<min>` and/or `insufficient_labels:<actual>/<min>`.
   - **Label Provenance**:
     - When scanning telemetry directories, `cisternal shadow check` filters candidate labels to those whose `label_source` is in `allowed_label_sources`. Labels with sources not in `allowed_label_sources` are ignored during join and do not count toward `min_labels` or confusion metrics.
     - If `--labels-file` is explicitly passed containing labels outside `allowed_label_sources`, or if labels from disallowed sources are forced into evaluation, the check records `unpermitted_label_sources_present:<sources>` in `blocking_reasons`.
   - **Precision Gates**:
     - If `min_precision` is configured: empirical precision must be $\ge \text{min\_precision}$. If deficient, records `precision_deficit:<actual>/<min>`.
     - If `min_precision_lower_bound` is configured: Wilson score lower bound must be $\ge \text{min\_precision\_lower\_bound}$. If deficient, records `precision_lower_bound_deficit:<actual>/<min>`.
   - **Recall Gates**:
     - If `min_recall` is configured: empirical recall must be $\ge \text{min\_recall}$. If deficient, records `recall_deficit:<actual>/<min>`.
     - If `min_recall_lower_bound` is configured: Wilson score lower bound must be $\ge \text{min\_recall\_lower\_bound}$. If deficient, records `recall_lower_bound_deficit:<actual>/<min>`.
     - If precision or recall is undefined due to zero occurrences, records `precision_undefined_no_positive_predictions` or `recall_undefined_no_positive_labels`.
   - **Base Rate Safety**: Empirical precision lower bound must strictly exceed empirical base rate. If not, records `precision_lower_bound_below_base_rate`.
   - **False Positive Rate**:
     - If $FP + TN > 0$: $FP / (FP + TN) \le \text{max\_fp\_rate}$. If exceeded, records `fpr_exceeded:<actual>/<max>`.
     - If $FP + TN = 0$ and `max_fp_rate` is configured: records `fpr_undefined_no_negative_labels` in `blocking_reasons`.
4. **Standard Exit Codes**:
   - **Exit 0**: Promotion permitted (`promotion_permitted: true`, `blocking_reasons = []`).
   - **Exit 1**: Promotion blocked (`promotion_permitted: false`, clean check, but blocked by one or more gate thresholds/conditions accumulated in `blocking_reasons`, including sample deficits, metric deficits, isolation violations, or `enforcer_unimportable:<symbol>`).
   - **Exit 2**: Refusal / Missing telemetry input (e.g., 0 labels or 0 verdicts matching feature in store).
   - **Exit 3**: Configuration / Environment error (missing or malformed mode-state TOML, unresolvable directory when Layer 5 `off` refuses operation, or invalid CLI syntax). Evaluation cannot proceed.
5. **Structured JSON Output (`--json`)**:
   When `--json` is passed, prints a structured payload (when $FP + TN = 0$, `"fp_rate"` is reported as `null`):
   ```json
   {
     "feature": "example_shadow_feature",
     "current_stage": "shadow",
     "target_stage": "advisory",
     "promotion_permitted": false,
     "blocking_reasons": ["insufficient_labels:10/15", "precision_lower_bound_deficit:0.68/0.70"],
     "metrics": {
       "verdicts_total": 45,
       "labels_total": 10,
       "tp": 8, "fp": 2, "tn": 0, "fn": 0,
       "base_rate": 1.0,
       "precision": 0.80,
       "precision_ci_lower": 0.68,
       "precision_ci_upper": 0.93,
       "recall": 1.0,
       "recall_ci_lower": 0.67,
       "recall_ci_upper": 1.0,
       "fp_rate": 1.0,
       "isolation_violations": 0
     }
   }
   ```
6. **Immutability Contract**:
   `cisternal shadow check` is strictly read-only. It NEVER mutates or writes to disk, git, or mode-state TOML files. Stage transitions require explicit manual edits in git.

### 3.4 Actor Isolation Harness (`prove_isolation`)

A pytest helper function and fixture in `cisternal.shadow.isolation`:
```python
@dataclass(frozen=True)
class IsolationResult:
    passed: bool
    live_output_identical: bool
    leaked_paths: list[Path]
    actor_output: Any
    shadow_output: Any

def prove_isolation(
    actor_live_fn: Callable[[], Any],
    actor_shadow_fn: Callable[[], Any],
    *,
    live_roots: list[Path],
    shadow_log_dir: Path,
    quiescence_wait_s: float = 0.0,
) -> IsolationResult:
    ...
```

Verification Protocol:
1. **Phase 1 (Baseline Live Run)**:
   - Takes baseline filesystem snapshot (paths, sizes, content SHA-256) of all directories in `live_roots` ($S_{live\_pre}$).
   - Executes `actor_live_fn()`, recording `actor_output`.
   - Takes post-run snapshot of `live_roots` ($S_{live\_post}$). Records baseline legitimate filesystem writes: $\Delta_{live} = S_{live\_post} - S_{live\_pre}$.
2. **Phase 2 (Shadow Run)**:
   - Cleans / resets `live_roots` to initial state (or utilizes an identical isolated workspace fixture).
   - Takes pre-shadow snapshot of `live_roots` ($S_{shadow\_pre}$).
   - Executes `actor_shadow_fn()`, recording `shadow_output`.
   - If `quiescence_wait_s > 0`, waits for background file flushes.
   - Takes post-shadow snapshot of `live_roots` ($S_{shadow\_post}$). Records shadow filesystem writes: $\Delta_{shadow} = S_{shadow\_post} - S_{shadow\_pre}$.
3. **Verification & Audit**:
   - **Live Output Identity**:
     - Return values: verifies `actor_output == shadow_output` (byte-identical for files/bytes/strings, structurally equal for objects).
     - Filesystem output in `live_roots`: verifies $\Delta_{live} == \Delta_{shadow}$ (the actor wrote the exact same files with identical paths, sizes, and SHA-256 hashes).
     - Sets `live_output_identical = (actor_output == shadow_output) and (Delta_live == Delta_shadow)`.
   - **Side-Effect Confinement**:
     - Compares $\Delta_{shadow}$ against $\Delta_{live}$. Any file created, modified, or deleted within `live_roots` during `actor_shadow_fn()` that was NOT present in $\Delta_{live}$ constitutes an isolation leak and is appended to `leaked_paths`.
     - Scans filesystem outside `live_roots` and `shadow_log_dir`. Any modification outside these allowed directories is appended to `leaked_paths`.
     - All shadow-arm telemetry and scratch writes must be strictly confined to `shadow_log_dir`.
   - **Result**: `passed = live_output_identical and (len(leaked_paths) == 0)`.
   - Optionally emits a `shadow.isolation` event via `cisternal.emit_event` with the result.

### 3.5 Agent Skill (`developing-in-shadow`)

A skill file located at `.praxia/skills/developing-in-shadow/SKILL.md` within the cisternal plugin:
- Documents the end-to-end shadow development lifecycle:
  1. Pre-registering mode-state TOML and thresholds before first verdict.
  2. Initializing telemetry with `cisternal.init(...)` at startup; inspecting boolean return status from `emit_verdict` and `emit_label`.
  3. Emitting `shadow.verdict` in candidate paths without modifying actor output.
  4. Capturing labels at work time (`at_work`) or from frozen test suites (`frozen_gold`).
  5. Running `cisternal shadow score` and interpreting precision vs base rate.
  6. Verifying isolation with `prove_isolation`.
  7. Checking promotion gates with `cisternal shadow check`.
- Includes a worked example: Bearings AC-9 (bathos spec 261104).

### 3.6 Resume and Preemption Semantics

1. **Append-Only Immutability**:
   Telemetry JSONL streams are append-only. Long-running shadow evaluations never rewrite or mutate existing records. Process interruption (preemption, SIGTERM, walltime exhaustion) leaves prior records intact and consistent.
2. **Idempotent Resumption on `(feature, subject_key)`**:
   The scorer and gate evaluator join on `(feature, subject_key)` and resolve multiple verdicts by taking the record with the latest timestamp (§3.2 item 1). If a batch evaluation run is preempted and resumed, re-evaluating an already-processed `subject_key` appends a new verdict that transparently supersedes the earlier partial or stale verdict without corrupting the historical record. Long-running batch runners may optionally maintain an offset checkpoint file or `--resume` flag that scans existing telemetry logs to skip already-emitted `subject_key`s.
3. **Preemption Safety & Stateless Tools**:
   CLI operations (`cisternal shadow score` and `check`) are purely read-only, streaming operations. They maintain no persistent locks, hold no open write handles to existing logs, and exit cleanly upon receiving `SIGINT` or `SIGTERM`.
4. **Fixture Isolation During Preemption**:
   `prove_isolation` operates within designated temporary directory fixtures. If preempted mid-test, pytest fixtures clean up temporary directories, guaranteeing that incomplete shadow runs never leak intermediate state or artifacts into production git roots.

### 3.7 Derived-Data 5-Layer Resolution Contract

In accordance with Fixed Owner Decision 5, derived-data locations are never hardcoded in library code and follow a strict 5-layer hierarchy:
`Layer 1 (Explicit CLI arg / API param) > Layer 2 (Environment variable) > Layer 3 (pyproject.toml) > Layer 4 (User config) > Layer 5 (Fallback: off)`

#### Resolution Tables

| Resolution Layer | Mode-State Directory (`mode_state_dir`) | Telemetry Log Directory (`log_dir`) |
|---|---|---|
| **Layer 1: CLI / API** | `--mode-state-dir <dir>` or positional TOML path | `--records-dir <dir>` or `--verdicts-file` / `--labels-file` |
| **Layer 2: Environment Variable** | `CISTERNAL_MODE_STATE_DIR` (empty or `"none"` disables) | `CISTERNAL_TELEMETRY_LOG_DIR` or `CISTERNAL_LOG_DIR` (empty or `"none"` disables) |
| **Layer 3: `pyproject.toml`** | Table `[tool.cisternal.shadow]`, key `mode_state_dir` | Table `[tool.cisternal.telemetry]`, key `log_dir` |
| **Layer 4: User Config** | `${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`, table `[shadow]`, key `mode_state_dir` | `${XDG_CONFIG_HOME:-~/.config}/cisternal/config.toml`, table `[telemetry]`, key `log_dir` |
| **Layer 5: Fallback** | `off` (refuses operation with exit code 2 or 3) | `off` (refuses operation with exit code 2) |

#### Diagnostics & Error Contract:
1. **Provenance Reporting**: Commands print or log which layer resolved each path (e.g., `resolved mode_state_dir from pyproject.toml (.praxia/mode_state)`).
2. **Environment Variable Precedence**: For telemetry log directory, `CISTERNAL_TELEMETRY_LOG_DIR` takes precedence, falling back to legacy alias `CISTERNAL_LOG_DIR`.
3. **Fail Loudly on Malformed Configuration**: If a configuration file exists in any layer but cannot be parsed as valid TOML, cisternal fails immediately with exit code 3 and diagnostic details naming the file and error.
4. **Explicit Off**: If resolution falls through to Layer 5 (`off`), operations requiring that path refuse execution with an explicit error listing all checked layers.

---

## 4. Controls & Acceptance Criteria

### 4.1 Positive and Negative Controls

1. **Scorer Negative Control 1 (Zero Labels)**:
   - Input: Verdict records exist in telemetry store, but 0 matching label records exist for the feature.
   - Expected Output: Must refuse to score; exit code 2; error message naming 0 matching labels. Never outputs 0.0 or 1.0 precision/recall.
2. **Scorer Negative Control 2 (Zero Positives / Division by Zero Handling)**:
   - Input: Labeled set containing 20 negative labels and 0 positive labels ($TP=0, FN=0, TN=20, FP=0$).
   - Expected Output: Precision evaluated to `null` / `"n/a (no positive predictions)"`, Recall evaluated to `null` / `"n/a (no positive labels)"`, base rate reported as 0.0, without raising `ZeroDivisionError`.
3. **Scorer Positive Control (Known Confusion Matrix)**:
   - Input: Synthetic stream with 40 TP, 10 FP, 5 FN, 45 TN ($N_{labeled}=100$, Base Rate = 0.45).
   - Expected Output: Precision = 0.80 [CI: Wilson bounds, e.g. 95% $\approx [0.67, 0.89]$], Recall = 0.8889 [CI: Wilson bounds, e.g. 95% $\approx [0.76, 0.95]$], reported correctly alongside Base Rate 0.45.
4. **Gate Check Negative Control (Multi-Failure Non-Short-Circuiting)**:
   - Input: Mode-state requiring `min_precision = 0.85` (actual precision 0.75), `min_precision_lower_bound = 0.70` (actual lower bound 0.68), `min_labels = 15` (actual labels 10), and `writes_isolated_enforced_by = "tests/does_not_exist.py::symbol"`.
   - Expected Output: Promotion blocked (`promotion_permitted = false`); `blocking_reasons` accumulates failures (`precision_deficit:0.75/0.85`, `precision_lower_bound_deficit:0.68/0.70`, `insufficient_labels:10/15`, and `enforcer_unimportable:tests/does_not_exist.py::symbol`) without short-circuiting on the first failure.
5. **Gate Check Positive Control (All Criteria Met)**:
   - Input: Mode-state where all sample counts, metric lower bounds, base-rate exceedance, and isolation checks are satisfied.
   - Expected Output: `promotion_permitted = true`, `blocking_reasons = []`, exit code 0.

### 4.2 Acceptance Criteria (Testable)

Every acceptance criterion is testable and explicitly names the deciding test target or CLI command:

- **AC-1 (Verdicts & Labels Pipeline)**: Calling `cisternal.shadow.emit_verdict(...)` and `cisternal.shadow.emit_label(...)` returns boolean acceptance status and appends valid JSON records conforming to §3.1 into the resolved JSONL log.
  - *Deciding Command*: `uv run pytest tests/shadow/test_events.py`
- **AC-2 (Scorer Joining, Wilson Intervals & Refusal)**: `cisternal shadow score <feature>` joins records on `subject_key`, streams multi-process logs from `--records-dir`, extracts predictions and positive classes, calculates Wilson score confidence intervals, handles zero-denominators gracefully, reports base rate, and exits with code 2 on zero labels.
  - *Deciding Commands*: `uv run pytest tests/shadow/test_score.py` and `uv run python .venv/bin/cisternal shadow score <feature> --records-dir <dir>`
- **AC-3 (Mode-State Evaluation & Non-Short-Circuiting)**: `cisternal shadow check` parses mode-state TOML, resolves enforcer symbols via `<file_path>::<symbol>`, evaluates all gates without early short-circuiting, computes `promotion_permitted` and `blocking_reasons` without mutating disk, and complies with exit code contract (0, 1, 2, 3).
  - *Deciding Commands*: `uv run pytest tests/shadow/test_check.py` and `uv run python .venv/bin/cisternal shadow check <feature_or_path>`
- **AC-4 (Isolation Harness)**: `prove_isolation(actor_live_fn: Callable[[], Any], actor_shadow_fn: Callable[[], Any], *, live_roots: list[Path], shadow_log_dir: Path, quiescence_wait_s: float = 0.0) -> IsolationResult` executes baseline live run vs shadow run, verifies byte-identical live outputs and identical filesystem deltas ($\Delta_{live} == \Delta_{shadow}$), detects leaks outside allowed directories (`live_roots` and `shadow_log_dir`), and returns structured `IsolationResult`.
  - *Deciding Command*: `uv run pytest tests/shadow/test_isolation.py`
- **AC-5 (Plugin Assets & Adoption Skill)**: The adoption skill is registered at `.praxia/skills/developing-in-shadow/SKILL.md` with valid frontmatter, character limits compliant with listing rules, and worked Bearings AC-9 example.
  - *Deciding Command*: `uv run python .venv/bin/cisternal assets validate --manifest .praxia/manifest.toml`

---

## 5. Adoption Roadmap

1. **Bearings AC-9 (bathos 261104)**: Initial adopter. Reader mapping of sidecars to charter purposes.
2. **Bathos blast-radius**: Migrate `shadow_verdict` and `shadow_trigger` to shared events, attach labels to measure trigger precision.
3. **Maraxiom reader_text**: Migrate `_reader_text/<build_id>.jsonl` and human classification to shared events and `cisternal shadow score`.
4. **Praxia mode-state**: Map stage ladder to shared events and telemetry exporter.

---

## 6. Resolved Design Questions (Round 1 Review)

1. **Mode-State Storage Location**:
   - *Resolution*: Stored in the consuming repository under `.praxia/mode_state/<feature>.toml` (for praxia-family repos) or `.cisternal/mode_state/<feature>.toml`, resolved via the 5-layer hierarchy (§3.7) with `pyproject.toml: [tool.cisternal.shadow] mode_state_dir`.
   - *Basis*: Mode-state TOML files define formal, version-controlled promotion gates and pre-registered thresholds that must be reviewable in git PRs and reproducible across team checkouts. Storing mode-state in user config breaks reproducibility. Furthermore, Fixed Owner Decision 5 prohibits hardcoding default library paths and mandates the 5-layer resolution hierarchy.
2. **Subject Key Namespacing**:
   - *Resolution*: Primary key scoping is structurally defined by the tuple `(feature, subject_key)`. Within each feature, the recommended convention is `<entity_type>:<id>` (e.g., `run:01a79c37`, `sha256:e3b0c442`, `sidecar:261104.bth.toml`).
   - *Basis*: Because `cisternal shadow score` and `check` filter strictly on `feature == <feature>`, cross-feature collisions are prevented by construction. Within a feature, adopting `<entity_type>:<id>` avoids accidental collisions between different item classes and makes telemetry logs transparently self-describing.
3. **Small-n Confidence Interval Method**:
   - *Resolution*: Standardize exclusively on the Wilson score interval (default 95% confidence) for all sample sizes $n$.
   - *Basis*: Clopper-Pearson exact binomial intervals require computing inverse incomplete beta function quantiles, which introduces an undeclared dependency on `scipy` (absent from `pyproject.toml`). The Wilson score interval provides an exact closed-form algebraic formula requiring only Python stdlib `math`, strictly bounds intervals within $[0, 1]$, and has proven empirical coverage down to small $n$ across Praxia and Maraxiom calibration pipelines (`specs/261026_review-reader-layer.md §6`).
4. **Advisory Stage Gating**:
   - *Resolution*: Promoting from `shadow` to `advisory` MUST require passing a pre-registered promotion gate.
   - *Basis*: Fixed Owner Decision 2 defines `advisory` as presenting candidate outputs directly to human actors or higher-level agents (non-blocking). Historical evidence from Praxia's Fast-and-Frugal Tree defect (`skills/developing-fast-frugal-trees/SKILL.md:79`) demonstrated that presenting uncalibrated advice (0.10 precision vs 0.56 base rate) actively degraded human trust and induced harmful cognitive anchoring. Entering advisory must therefore be earned through pre-registered calibration on ground truth labels.
