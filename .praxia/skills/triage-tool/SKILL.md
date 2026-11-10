---
name: triage-tool
description: "Use when auditing agent MCP/skill use or pruning unused tool servers before changing project settings."
covers_families: []
distinctive_strings:
  - "triage-tool"
  - "prune-list"
  - "cisternal usage"
---

# Triage tool

## When to Use

Use `triage-tool` when auditing agent MCP/skill use or pruning unused tool servers before changing project settings.

## Scope

Audits tool usage via `cisternal usage` and evaluates server pruning candidates via `cisternal prune-list`. Produces non-destructive recommendations for user review. Never writes or modifies `~/.claude/settings.json` or `~/.claude.json`.

## Overview

The tool triage workflow identifies inactive MCP servers and underutilized tools across client session transcripts. By reviewing empirical usage telemetry before disabling or removing servers, teams maintain a lean tool surface while guarding against inadvertent removal of required capabilities.

Detailed steps, triage thresholds, and decision heuristics are documented in `references/triage_workflow.md`.

## Workflow Summary

1. **Audit Usage Telemetry**: Run `cisternal usage` to inspect MCP, CLI, and skill activity across sessions.
2. **Generate Prune Recommendations**: Run `cisternal prune-list` to categorize active servers into `drop`, `enable-per-project`, or `keep`.
3. **Manual Verification**: Review candidate servers with project maintainers. Do not automate deletion of configuration files.
