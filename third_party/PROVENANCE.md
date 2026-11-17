# Vendored third-party provenance

## seoextract 0.3.0

| Field | Value |
|---|---|
| Upstream repository | https://github.com/Britto1221/seoextract |
| Upstream commit | `6544a74e340e6ac8b147b7f4ab0f09d55d142dd3` |
| Upstream tag / release | v0.3.0 (PyPI 0.3.0) |
| Vendored on | 2026-11-16 |
| Vendored path | `third_party/seoextract/` |
| PyPI wheel sha256 | `8b454966f1fcbdeeccb0569a99b8e287033b6a0298c24af0ab1a8e021d6bd3ca` |
| PyPI sdist sha256 | `35cef96d5f5aa74f89540efb12e51dfc11e87a57e64aa9b3754605fa3a0782bc` |
| Local diff vs upstream | one added file: `VERSION` (see "Local additions" below); upstream files verbatim |

### Local additions

| File | Content | Reason |
|---|---|---|
| `VERSION` | the upstream commit hash `6544a74e340e6ac8b147b7f4ab0f09d55d142dd3` | lets the packaging guard byte-check the vendored bytes against `config.SEOEXTRACT_COMMIT` instead of only probing `__version__` and symbols; closes the "pinned but not hermetic" caveat from the v1.2 review |

Added 2026-11-17. Not from upstream; not imported by seoextract at runtime.
The bundled wheel copy under `src/resources/third_party/seoextract/` carries
the identical file. Both copies are asserted by `tests/test_packaging.py`.

### Real API names (verified against vendored source)

The 0.3.0 API differs from the original v1.1 draft in two ways, recorded here as
required by the spec:

1. `AuditResult`, `PageData`, `SEOIssue` and `Severity` live in
   `seoextract.models`, not at package top level. Only `SEOExtract` is exported
   from `seoextract/__init__.py`.
2. `PageData` exposes `meta_description` (not `meta_desc`), `h1_tags` (list),
   `response_time_ms`, and `AuditResult` exposes `audit_date`.

`src/audit_adapter.py` is the only file that imports these names. Its
capability probe (`probe_capabilities`) raises `ImportError` naming any missing
symbol. A future upstream change should therefore break one file and one test,
not the pipeline.

### Import strategy

`src/audit_adapter.py` prepends `third_party/seoextract` to `sys.path` and then
imports the package. Nothing is installed from PyPI at runtime. See
`requirements-seoextract.txt`.

### Edit policy

Do not edit `third_party/seoextract/**` in place. Any local patch requires:

1. a new section in this file with the reason and diff summary,
2. a `CHANGELOG.md` entry,
3. an upstream issue/PR link where possible.

Gaps in seoextract (broken links, sitemap, robots report, audit diff) are
implemented in our own code, never patched into the fork (D-1).
