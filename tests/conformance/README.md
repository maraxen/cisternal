# Rust parity conformance fixtures (M12.1)

Pinned `PraxiaBundle` JSON and expected `surface_bundle_sha256` digests from
praxia-agent-assets at `CISTERNA_PRAXIA_ASSETS_REV=04bb683f11d6e879dcfc5dafbedfed426254985a`.
cisterna legacy `tests/golden/` digests remain Python-canonical.
`tests/golden/rust_parity/` uses in-process rust-parity emit + `bundle_sha256_rust`
for all four surfaces on the `legacy` slug.

Rust-parity emit ignores `hooks_for_surface()` (all `hook_specs` pass through, matching
`bundle-hash`). Cursor rust-parity omits `agents/*.agent.md` (praxia fail-closed default).

The `rust-parity` CI job (blocking as of M12.4) runs subprocess and in-process
parity tests against the praxia pin above.

**Dual-lane export trust:** `golden_matrix` validates Python-canonical legacy export;
`rust-parity` validates praxia byte parity via `tests/golden/rust_parity/`.
