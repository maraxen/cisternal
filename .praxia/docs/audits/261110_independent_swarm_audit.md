---
title: "Tool-Surface Triage: Independent Swarm Forensic Audit & Zero-Trust Verification"
description: "Zero-trust forensic audit of the Cycles 1-9 tool-surface triage implementation in cisternal across Tracks A-D, adversarial probes, hermeticity verification, and completed remediations."
status: complete
task_id: 261106_tool-surface-triage
date: '261110'
author: "worker_remediation / swarm_auditor"
verdict: PASS
---
# Independent Swarm Forensic Audit & Zero-Trust Verification: Tool-Surface Triage

- **Target Spec**: `.praxia/docs/specs/261106_tool-surface-triage.md` (Cycles 1–9)
- **Worktree**: `/home/marielle/projects/cisternal/.claude/worktrees/261106-agy-spec-cycles`
- **Branch**: `wt/261106_agy-spec-cycles`
- **Audit Date**: 2026-11-10
- **Verdict**: **PASS** (Zero open defects; all findings remediated and regression-tested)

---

## 1. Executive Summary & Audit Methodology

This report documents the forensic, zero-trust audit conducted across the full implementation of the Tool-Surface Triage system (`Pre-0`, `Pre-1`, `C0`–`C6`), spanning transcript discovery, command tokenization, error normalization adapters, prune analytics, skill coverage gates, and client hook telemetry.

The audit was executed with zero trust toward prior assertions:
1. **Source Inspection**: Every newly introduced and modified file in `src/cisternal/` and `tests/` was audited line-by-line against the invariants of `.praxia/docs/specs/261106_tool-surface-triage.md`.
2. **Adversarial & Fault Injection Probes**: Targeted tests challenged POSIX atomic appends, corrupt UTF-8 error ledgers, unquoted command substitutions, sudo flag chaining, non-dictionary JSONL records, and protocol error envelopes.
3. **Hermeticity & Anti-Facade Verification**: Confirmed that no tests write to host configuration files (`~/.claude/*`, `~/.config/cisternal/*`), no tests spawn un-isolated `claude` subprocesses, and no hardcoded outputs or facades exist.
4. **Remediation Loop**: All 10 findings surfaced during the Phase 1 review (A1–A5, C1, D1–D4) were remediated with minimal compliant code changes and paired regression tests.

---

## 2. Track Findings, Remediations & Evidence Chains

### Track A: Transcripts, Path Precedence, Tokenizer & Stratification

| Finding | Severity | Description | Remediation Applied | Regression Test |
|---|---|---|---|---|
| **A1** | Medium | `stratify_session_type` assumed `dict[str, Any]` items, failing when given streamed `TranscriptEvent` instances. | Updated `stratify_session_type` to accept `Iterable[TranscriptEvent \| dict[str, Any]]`, extracting `item.raw_record if isinstance(item, TranscriptEvent) else item`. Simplified `usage.py` call site. | `tests/test_usage_stratification.py::TestStratifySessionType::test_transcript_event_instances_accepted` |
| **A2** | Medium | `sudo` wrapper stripping in `parse_cli_commands` treated `sudo` as a simple single-word wrapper, aborting verb extraction on commands with flags/user arguments (e.g. `sudo -u user bth sql`). | Extracted `sudo` into a dedicated wrapper-consumption loop that swallows flags (`-u <user>`, `-g <group>`, `-E`, `-i`, `-s`, `-n`, `--user=...`, etc.) and attached clusters. | `tests/test_usage_tokenizer.py::TestUsageTokenizer::test_sudo_with_flags_and_user` |
| **A3** | Medium | `parse_cli_commands` did not recognize `--flag=value` syntax in `global_flags_with_value`, skipping subcommands when equals syntax was used. | Implemented `arg.partition("=")` in the token scan loop after the binary token to handle both `--flag=value` and `--flag value`. | `tests/test_usage_tokenizer.py::TestUsageTokenizer::test_flag_equals_value_syntax` |
| **A4** | Low | `_GIT_COMMON_DIR_CACHE` in `transcript.py` was mutated during tests without guaranteed teardown cleanup. | Added an `autouse=True` fixture in `tests/test_usage_repo_key.py` clearing `_GIT_COMMON_DIR_CACHE` during teardown. | `tests/test_usage_repo_key.py` |
| **A5** | Medium | Lack of direct unit tests covering `stream_transcript_events` resilience against empty lines, whitespace, malformed JSON syntax, and non-dict records. | Added `TestStreamTranscriptEvents` covering empty files, whitespace-only lines, corrupt JSON, strings, ints, lists, booleans, and nulls. | `tests/test_usage_stratification.py::TestStreamTranscriptEvents::test_malformed_json_and_non_dict_records` |

**Track A Invariant Verification**:
- **5-Layer Precedence**: `resolve_sessions_dir` verifies `arg > env > pyproject > xdg > off`. In hook mode (`is_hook=True`), Layer 3 is anchored to `$CLAUDE_PROJECT_DIR` and skipped when unset, preventing cwd divergence.
- **POSIX Append**: `atomic_append_jsonl` operates in `os.O_WRONLY | os.O_CREAT | os.O_APPEND` mode with writes strictly capped to `<= 4096` bytes and boundary-safe UTF-8 truncation, backed by a 1 MiB total file cap.
- **Compound Tokenizer**: Successfully splits `&&`, `||`, `;`, `|`, `&`, `\n`, ignores redirection ampersands (`2>&1`), fails open on unclosed quotes, and skips segments with unquoted substitutions `$(...)` or backticks prior to the verb.
- **Repo Key Folding**: `resolve_repo_key` cleanly folds `.claude/worktrees/*` and `.worktrees/*` into the common git directory parent.

---

### Track B: Telemetry Adapters & Pure Error Normalization

- **Contract**: Audited `src/cisternal/adapters/base.py` for `NormalizedError` and pure methods `normalize_error` and `normalize_exception`.
- **Zero I/O Guarantee**: Verified that all adapter classes (`AdapterBase`, `BathosAdapter`, `PassthroughAdapter`, `ContemplexAdapter`, `XpeririAdapter`, `MyxcelAdapter`) execute with zero filesystem and network operations.
- **Adversarial Resilience**: Tested with non-string error payloads, deep cyclic dictionaries, missing fields, and arbitrary exceptions. All tests in `tests/test_adapters_normalization.py` pass.

---

### Track C: Usage Derivation, Prune Recommendations, Assets & Skills

| Finding | Severity | Description | Remediation Applied | Regression Test |
|---|---|---|---|---|
| **C1** | Medium | `benchmarks/usage/c0_usage.bth.toml` sidecar schema omitted the required `decision` string across all four outcome tables (`[outcomes.pass]`, `[outcomes.marginal]`, `[outcomes.inconclusive]`, `[outcomes.fail]`). | Added standard decision strings: `"proceed"`, `"investigate"`, `"expand-window"`, and `"abandon"`. | Validated TOML parse and sidecar schema conformance. |

**Track C Invariant Verification**:
- **C0 Usage Derivation**: Re-derivation of E1–E5 across transcripts with 95% Wilson confidence intervals; paired synthetic positive control ($N=5$) and negative control ($N=0$) correctly gate valid runs.
- **C1 Active Registrations & Prune Recommendations**:
  - `scan_active_registrations()` guarantees read-only access (uses `marketplace_root_source()`, never mutates host config, never spawns `claude` subprocess).
  - Prune recommendation engine enforces dual floors ($N \ge 20$ sessions AND $\ge 14$ calendar days), applying Rule-of-Three upper bounds and concentration shares.
- **C2 Assets Validation**: Dangling tool references are fatal under `LoadReport.warnings`, while uncovered families are warn-only under `LoadReport.advisories`.
- **C3 Skill Coverage Evaluation**: Synthetically evaluated across 80 situations; achieves precision 1.0000 and recall 1.0000 over 60 matched turns, clearing the $\ge 0.80$ threshold.
- **C4a / C6 Skills Hygiene**:
  - `writing-skill-triggers` PascalCase extraction regex `\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b` with markdown code fence stripping.
  - `triage-tool` skill strictly obeys `listing_chars <= 150` non-destructive character cap.

---

### Track D: Hooks Substrate, Latency & Error Classification

| Finding | Severity | Description | Remediation Applied | Regression Test |
|---|---|---|---|---|
| **D1** | Medium | `handle_post_tool_use` called `canonical_tool_key(tool_name)` without `declared_servers`, preventing longest-suffix matching for multi-segment plugin names (e.g. `mcp__plugin_myplugin_bathos__run_sql`). | Wired active registrations to extract `declared_servers=regs.servers` before calling `canonical_tool_key`. Accepted optional `registrations` parameter. | `tests/test_hooks.py::TestPostToolUseErrors::test_post_tool_use_declared_servers_longest_suffix` |
| **D2** | Medium | `is_suppressed` used raw `read_text(encoding="utf-8")`, which crashed with `UnicodeDecodeError` when corrupt binary bytes were present in the error ledger. | Added `encoding="utf-8", errors="replace"` and caught `(OSError, UnicodeDecodeError)` to fail open safely. | `tests/test_hooks.py::TestPostToolUseErrors::test_is_suppressed_unicode_decode_error_resilience` |
| **D3** | Medium | `is_proto_error` checked only `payload["tool_response"]`, missing protocol errors returned under `payload["tool_result"]`. | Defined `tool_response = payload.get("tool_response") or payload.get("tool_result")` before `is_proto_error` check. | `tests/test_hooks.py::TestPostToolUseErrors::test_post_tool_use_tool_result_proto_error` |
| **D4** | High | CLI startup overhead when invoking hooks via `cisternal hook ...` was heavy due to eager loading of the Cyclopts CLI framework and PyYAML. | 1. Implemented dedicated lightweight entry point `src/cisternal/usage/cli_hook.py`.<br>2. Converted `cisternal.usage` and `cisternal.plugin` package exports to PEP 562 lazy `__getattr__` loading.<br>3. Removed eager `AssetBundle` runtime import from `cisternal.plugin.shared`.<br>4. In-process p95 warm latency: **0.73 ms**; cold rebuild p95: **6.00 ms** (budget: $\le 150$ ms). | `tests/test_hooks.py::TestHookPerformanceBenchmark` and `tests/test_adversarial_m5_hooks.py` |

---

## 3. Forensic Anti-Facade & Hermeticity Verification

1. **Host Isolation**:
   - `~/.claude/settings.json`, `~/.claude.json`, and `~/.config/cisternal/config.toml` on the host machine were audited before and after test executions. Zero mutations occurred.
   - All tests use hermetic `tmp_path` fixtures via `mock_hook_env` and monkeypatched environment variables.
2. **Subprocess Isolation**:
   - Audited all tests to confirm zero `claude` CLI subprocesses were spawned. All marketplace and install paths mock or simulate subprocess output cleanly.
3. **Anti-Facade Review**:
   - No hardcoded test responses: calculations for Wilson intervals, rule-of-three upper bounds, E4 transition contingency tables, and error ledger lookups maintain genuine state and produce mathematically verified values.

---

## 4. Comprehensive Verification Gate Results

### A. Targeted Pytest Suite
```
uv run pytest -q tests/test_usage_*.py tests/test_canonical_tool_key.py tests/test_adapters_*.py tests/test_hooks.py tests/test_adversarial_*.py
```
**Result**: **391 passed in 6.12s** (100% pass rate).

### B. Lint Check
```
uv run ruff check
```
**Result**: `All checks passed!` (0 errors, 0 warnings).

### C. Asset Manifest Validation
```
uv run python -m cisternal.cli assets validate --manifest .praxia/manifest.toml
```
**Result**: Clean pass with expected informational advisories:
- Advisories on `customizing-tools` and `run-cisternal` listing lengths.
- Advisories on unmonitored families (`bathos_query`, `contemplex_brainstorm`, `myxcel_slurm`).
- Zero warnings, zero errors. Exit code 0.

### D. Snapshot Parity Check
```
uv run python -m cisternal.cli assets snapshot --manifest .praxia/manifest.toml --out src/cisternal/agent_plugin.json --check
```
**Result**: `snapshot up to date: src/cisternal/agent_plugin.json` (Exit code 0).

### E. Skill Coverage Evaluation Gate
```
uv run python -m cisternal.cli skill-coverage --manifest .praxia/manifest.toml --situations tests/fixtures/situations/synthetic_situations.jsonl
```
**Result**:
- Monitored skills: 5
- Total situations: 80
- Matched turns ($n$): 60
- Precision ($\hat{p}$): 1.0000 [94.0%, 100.0%]
- Recall: 1.0000 [94.0%, 100.0%]
- Threshold: 0.80
- **Gate Status: PASS**

---

## 5. Audit Verdict & Certification

**Final Audit Verdict: PASS**

All findings from Phase 1 zero-trust review are remediated, verified by automated tests, and proven strictly spec-compliant. The worktree is in a verified, clean, merge-ready state.
