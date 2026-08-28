---
archive: handoffs_migrated_260828_001.tar.zst
created: 260828
source: .praxia/handoffs/
size_bytes: 9159
contents:
    - path: handoffs/cisterna_M2 complete_20260618_181537_9e0f7366-caa1-4bf3-9c89-bc5ed6c895c5.yaml
      size_bytes: 2564
    - path: handoffs/cisterna_M2 spec → backlog_20260618_163240_d9693b73-fad0-438f-a38c-66e6739d65a7.yaml
      size_bytes: 3675
    - path: handoffs/cisterna_M3 — agent-asset export (epic complete)_20260619_120917_cebc0a88-d392-436f-8884-7f49ab6f68b8.yaml
      size_bytes: 3773
    - path: handoffs/cisternal_Phase-6_20260824_142733_5d06bb95-5717-4af4-8e4e-83b45cf43c64.yaml
      size_bytes: 1151
    - path: handoffs/cisternal_Phase-6_20260824_212534_a58fb9ce-569d-4990-939d-d773f52a3ecc.yaml
      size_bytes: 1321
    - path: handoffs/cisternal_shipped-cisternal-side_20260819_145021_d1d13c65-5197-46ba-8c2c-30d9ba22bee9.yaml
      size_bytes: 4966
    - path: handoffs/cisternal_shipped_20260813_221007_c26e42ca-4fd7-4dd1-9bdb-6197b3765c2b.yaml
      size_bytes: 4375
---

7 per-event handoff YAML files, migrated into `.praxia/handoffs.jsonl`
on 2026-08-28 (see `scripts/migrate_handoffs_to_jsonl.py`).
Every record was verified present in the new ledger before these originals
were archived and removed from the working tree.
