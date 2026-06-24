# M11.2 native-validate surface expansion — closeout (#2713)

**date:** 2026-06-23  
**verdict:** **APPROVE**

## AC matrix

| AC | Status | Evidence |
|----|--------|----------|
| AC-M11.2-1 | PASS | `export-dogfood.yml` native-validate loops 4 surfaces |
| AC-M11.2-2 | PASS | claude `--emit-command-bodies` retained |
| AC-M11.2-3 | PASS | `test_cli_native_validate.py` parametrized × 4 surfaces |
| AC-M11.2-4 | PASS | `test_native_validate_job_covers_all_surfaces` |

## Scope

Expanded subprocess validate CI and unit tests from claude-only to all builtin surfaces on self-manifest. `emit_command_bodies` remains claude-only per `validate_golden` contract.
