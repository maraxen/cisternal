---
session_id: a8b30dc1
topic: M12 export Rust bridge / praxia-agent-assets parity for cisterna (#2665). Hash parity spike (2026-06-24) found ZERO digest match across claude/cursor/copilot/antigravity on manifest_minimal: (1) hash algo differs — cisterna bundle_sha256 uses path\\ncontents\\n, Rust surface_bundle_sha256 uses path\\0contents\\n; (2) emitter output differs — e.g. claude Python emits 1 file (names-only plugin.json), Rust emits 4 files (agents/skills/hooks + compact plugin.json with agents/skills keys). Cisterna goldens are self-consistent (413 tests). M11 golden matrix + M11.1 native-validate cover Python-only trust. Deferred as M11-H. PI-gated cross-repo. What should M12 optimize for: hash unification, emitter byte parity, PyO3 bridge, shared conformance vectors, scope (claude-first vs all surfaces), golden migration strategy?
task_type: architectural
winner: M12 phased D+F with subprocess validate lane: (1) praxia-agent-assets bundle-hash CLI emitting surface_bundle_sha256; (2) shared conformance fixtures in both repos; (3) cisterna validate --rust-parity advisory CI; (4) claude-first emitter byte-align + Rust hash adoption + golden refresh; (5) expand to 4 surfaces then promote job blocking. Exclude cisterna-provenance from parity scope.
created_at: 2026-06-24T13:33:54.079230+00:00
---

# Brainstorm: M12 export Rust bridge / praxia-agent-assets parity for cisterna (#2665). Hash parity spike (2026-06-24) found ZERO digest match across claude/cursor/copilot/antigravity on manifest_minimal: (1) hash algo differs — cisterna bundle_sha256 uses path\\ncontents\\n, Rust surface_bundle_sha256 uses path\\0contents\\n; (2) emitter output differs — e.g. claude Python emits 1 file (names-only plugin.json), Rust emits 4 files (agents/skills/hooks + compact plugin.json with agents/skills keys). Cisterna goldens are self-consistent (413 tests). M11 golden matrix + M11.1 native-validate cover Python-only trust. Deferred as M11-H. PI-gated cross-repo. What should M12 optimize for: hash unification, emitter byte parity, PyO3 bridge, shared conformance vectors, scope (claude-first vs all surfaces), golden migration strategy?

## Problem Frame
Fixed constraints:
- export-dogfood CI must stay green (dogfood, golden_matrix, native-validate, otlp-collector)
- cisterna CLI import path stays fastmcp-free
- praxia-agent-assets remains canonical Rust reference (not rewrite Rust to match Python)
- 4 built-in surfaces eventually need trust, not just claude

Negotiable:
- Bridge: PyO3 vs subprocess vs port-Python vs conformance-only
- Golden migration: big-bang refresh vs dual-track advisory job vs claude-first wedge
- Validate path: in-process Python digest vs optional --rust-parity flag vs flip default
- Scope phasing: claude → cursor/copilot/antigravity vs all-surfaces epic
- cisterna-provenance sidecar: keep Python-only or exclude from Rust parity scope

Success = operator can run cisterna validate and get same digest as praxia surface_bundle_sha256 on shared fixtures; CI enforces it.

## Idea Pool
- [ai] M12-D+F hybrid: Shared conformance vectors in both repos (manifest_minimal + dogfood slice) + phased emitter parity (claude first) + adopt Rust hash canonicalization in Python bundle_sha256 once bytes match per surface.
- [ai] M12-B: PyO3 extension `cisterna_rust_assets` exposing surface_bundle_sha256(PraxiaBundle JSON) — validate calls Rust, emit stays Python until ported.
- [ai] M12-C: Subprocess hash CLI in praxia-agent-assets (no PyO3) — cisterna validate --rust-parity shells out; advisory CI job first.
- [ai] M12-F pure: Port all Python emitters to byte-match Rust; switch bundle_sha256 to Rust algorithm; refresh 15 goldens — no runtime Rust dep.
- [ai] M12-H: Document divergence; advisory rust-parity job only; defer emitter alignment — lowest cost, incomplete success criteria.
- [ai] M12-G: Rust-only validate truth — Python emitters for export only, digest always from Rust subprocess.
- [ai] M12-E: Claude wedge only — align ClaudeEmitter + hooks to Rust 4-file output; other surfaces out of M12 scope.
- [user] Competing approaches (no evaluation yet):
- [user] **Conformance-first (D+F)**: Commit shared fixture bundles both repos test against; phase emitter port surface-by-surface; unify hash last per surface when bytes match.
- [user] **Rust runtime bridge (B)**: PyO3/maturin wraps `surface_bundle_sha256`; map AssetBundle→PraxiaBundle in Python; validate digest from Rust even while emitters diverge (would fail until emitters aligned OR Rust also emits).
- [user] **Subprocess bridge (C/G)**: Small `praxia-agent-assets hash` binary; cisterna validate pipes bundle JSON; no PyO3 build complexity; same alignment prerequisite.
- [user] **Python port-only (F)**: No Rust at runtime; painstakingly match Rust bytes in Python emitters + switch to `\0` hash; refresh goldens; dual maintenance forever.
- [user] **Advisory-only (H)**: Spike becomes docs; optional CI job reports mismatch without blocking; M12 reduces to monitoring.
- [user] **Claude wedge (E)**: Narrow M12 to worst gap (1 vs 4 files); prove one-surface end-to-end parity before expanding.
- [user] Probe: For (2)/(3), can digest match before emitter parity if we hash Rust-emitted files only? That would mean validate exports via Rust emit path, not Python emit — shifts truth to Rust earlier.
- [user] Trade-off probe answers:
- [user] Rust-hash-before-emit-parity only helps if validate uses Rust emitters (G/B variant). Hashing Python emit with Rust algo still fails (spike: even identical bytes → different digest). So runtime bridge without emit parity is a dead end unless validate path switches to Rust emit.
- [user] PyO3 (B) vs subprocess (C): subprocess wins for CI simplicity (no maturin wheel per platform in cisterna release); PyO3 wins for latency and typed FFI. Given cisterna is Python-primary, subprocess + shared fixtures is lower risk for M12.1.
- [user] Pure Python port (F) duplicates praxia maintenance — every bundle_claude.rs change needs Python follow-up. Violates "Rust is canonical" spirit.
- [user] Advisory-only (H) doesn't meet success criteria.
- [user] Claude wedge (E) is right phasing but insufficient alone for epic close — need conformance harness that scales to 4 surfaces.
- [user] Leaning: **M12.1 = shared conformance vectors (D) + subprocess Rust hash/emit validate lane (C/G) advisory → blocking**; **M12.2 = emitter port per surface starting claude (E+F)** until subprocess and in-process digests match, then flip goldens to Rust algorithm.
- [user] Ready to converge unless you see a blocker.

## Decision Log

## Assumptions

## TBDs

## Pre-mortem Record
**User:** Critic responses:

1. **B1 names-only break**: Accept golden refresh for claude names_only — spike shows Rust truth includes agent/skill/hook files. Document in M12 spec: "rust parity mode" uses full Claude bundle shape; names_only golden tuple may split into rust_parity vs legacy_python digests during transition, or names_only redefined to match Rust file set.

2. **CI cross-repo pin**: Pin praxia rev via submodule or CISTERNA_PRAXIA_ASSETS_REV env in export-dogfood; build only `bundle-hash` bin with cache. Acceptable cost for blocking promotion at M12.3.

3. **Dual maintenance**: Subprocess lane is the conformance oracle; Python emitters port until in-process matches — dual path is temporary per surface, not permanent (beats subprocess-only runner-up).

4. **fastmcp-free**: subprocess validate doesn't import Rust into Python interpreter — OK.

Confirm winner: phased D+F with subprocess lane.
**AI:** _not recorded_

## Acceptance Criteria
**Given** Fixed constraints:
- export-dogfood CI must stay green (dogfood, golden_matrix, native-validate, otlp-collector)
- cisterna CLI import path stays fastmcp-free
- praxia-agent-assets remains canonical Rust reference (not rewrite Rust to match Python)
- 4 built-in surfaces eventually need trust, not just claude

Negotiable:
- Bridge: PyO3 vs subprocess vs port-Python vs conformance-only
- Golden migration: big-bang refresh vs dual-track advisory job vs claude-first wedge
- Validate path: in-process Python digest vs optional --rust-parity flag vs flip default
- Scope phasing: claude → cursor/copilot/antigravity vs all-surfaces epic
- cisterna-provenance sidecar: keep Python-only or exclude from Rust parity scope

Success = operator can run cisterna validate and get same digest as praxia surface_bundle_sha256 on shared fixtures; CI enforces it.
**When** implementing M12 phased D+F with subprocess validate lane: (1) praxia-agent-assets bundle-hash CLI emitting surface_bundle_sha256; (2) shared conformance fixtures in both repos; (3) cisterna validate --rust-parity advisory CI; (4) claude-first emitter byte-align + Rust hash adoption + golden refresh; (5) expand to 4 surfaces then promote job blocking. Exclude cisterna-provenance from parity scope.
**Then**
  - [ ] _add specific measurable criteria_
