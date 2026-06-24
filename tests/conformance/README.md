# Rust parity conformance fixtures (M12.1)

Pinned `PraxiaBundle` JSON and expected `surface_bundle_sha256` digests from
praxia-agent-assets at `CISTERNA_PRAXIA_ASSETS_REV=04bb683f11d6e879dcfc5dafbedfed426254985a`.
cisterna legacy `tests/golden/` digests remain Python-canonical. Claude
`tests/golden/rust_parity/` (M12.2+) uses in-process rust-parity emit + `bundle_sha256_rust`.

The `rust-parity-advisory` CI job compares live subprocess output to
`expected/*.sha256`. Advisory until M12.4 blocking promotion.
