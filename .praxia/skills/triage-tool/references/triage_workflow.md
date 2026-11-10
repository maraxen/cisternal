# Tool Triage Workflow Reference

This reference describes the non-destructive audit and triage workflow for MCP tool servers and skill triggers.

## Principles

1. **Non-Destructive Recommendations**: Tool triage generates advisory suggestions for human review. It never directly mutates or deletes configuration files such as `~/.claude/settings.json`, `~/.claude.json`, or workspace project configs.
2. **Empirical Grounding**: Recommendations are grounded in actual session transcript data collected across projects over an observation window.
3. **Conservative Pruning Floors**: Servers are only recommended for global removal (`drop`) or repo-level scoping (`enable-per-project`) when empirical session counts and observation time spans meet rigorous statistical thresholds ($N \ge 20$ sessions and $\ge 14$ days).

## Triage Procedure

### Step 1: Gather Usage Data

Inspect recent activity across project sessions:

```bash
uv run cisternal usage --summary
```

This report details:
- Interactive vs headless tool calls
- E4 transition rates and error patterns
- Per-server and per-tool frequency distributions

### Step 2: Run Pruning Analysis

Run `cisternal prune-list` to evaluate server retention:

```bash
uv run cisternal prune-list
```

The command stratifies active MCP servers into three actionable categories:
- **`drop`**: Servers with 0 invocations across at least 20 recorded sessions spanning 14 or more days across all repositories.
- **`enable-per-project`**: Servers with 0 global activity but specific repository usage, indicating they should be scoped locally rather than globally enabled.
- **`keep`**: Actively utilized servers or servers with insufficient session history to meet the evaluation floor.

### Step 3: Review and Act Manually

Review the generated list with team members before applying configuration changes manually. Verify that:
- Any proposed `drop` candidate is not used exclusively in unrecorded ephemeral workflows.
- No project-critical hooks or CLI commands rely on the candidate servers.
- Changes to user settings are applied deliberately and manually.
