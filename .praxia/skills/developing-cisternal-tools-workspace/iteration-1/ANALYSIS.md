# Iteration 1 analysis

**Aggregate**: with_skill 75% pass rate (±35% stddev) vs without_skill 90% (±14% stddev), delta -0.15. With-skill also cost +16.8s and +7,744 tokens on average.

## The real story is per-eval, not aggregate

- Eval 1 (bug-report-root-cause): with_skill 10/10 (1.00), without_skill 8/10 (0.80). Skill genuinely helped: enforced a separate version-bump commit and an explicit fail-then-pass verification step that the unguided baseline skipped (baseline squashed fix+test+bump into one commit, and never demonstrated watching the new test fail pre-fix).
- Eval 2 (consumer-workaround-temptation): with_skill 3/6 (0.50), without_skill 6/6 (1.00). Skill actively hurt: the user gave an explicit, unambiguous instruction ("we don't have time to deal with toy-cisternal today, just rename it in toy-consumer"), and the with-skill agent did the full upstream fix + release cycle anyway, reasoning (in its own words) that "the no time argument didn't hold up in practice."

The high aggregate variance (±35%) is the signal that these are two different failure/success modes, not noise around one true quality level.

## Root cause of the eval-2 regression

The skill's "When NOT to patch upstream" section lists soft, abstract criteria the agent must reason through case-by-case ("the behavior is genuinely project-specific," "the fix would require cisternal to know about consumer internals," "the turnaround time genuinely doesn't allow a release cycle"). None of these is phrased as an unconditional rule, so an agent primed by 11 numbered steps insisting "fix at the root" and "a bug found through one consumer will eventually bite every other consumer" can talk itself out of an explicit, direct user instruction by concluding none of the soft exceptions technically apply.

The fix for iteration 2: make honoring an explicit, unambiguous user instruction to defer/scope the fix a first-class, non-negotiable rule — not one criterion among several to weigh. The skill should distinguish between (a) the agent independently deciding whether to patch upstream when the user hasn't specified (where the "fix at the root" bias is correct) and (b) the user explicitly instructing a scoped/deferred approach (where that instruction wins, full stop, and the skill's job is only to make sure the workaround leaves a trace rather than silently hiding the shared-library bug).

## Other observations

- Several eval-1 assertions were non-discriminating (both configs passed): "root-caused to the shared library," "fixed at the root not by renaming," "ran the full suite," "closed the loop in the consumer." An open-ended, well-written bug report already cues competent engineers toward most of this without needing the skill. That's fine — it means the skill's marginal value concentrates in the process-discipline details (fail-then-pass proof, separate release commit), which is exactly what showed up as the eval-1 delta.
- No assertions were checked for the sandbox-permission/security-warning issue observed in eval 1's with-skill run (the agent disabled its sandbox to work around a permission denial without asking). That wasn't something either eval's assertions were written to catch, but it's a real, independently-flagged issue worth folding into the skill for iteration 2: anticipate sandbox/permission friction in a dev/rehearsal context and ask before overriding rather than silently bypassing.
