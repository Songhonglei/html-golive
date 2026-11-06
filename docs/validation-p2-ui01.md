# P2 independent-acceptance follow-up: UI01 and H01–H03

Tracked in [#18](https://github.com/Songhonglei/html-golive/issues/18), continuing [PR #17](https://github.com/Songhonglei/html-golive/pull/17).

## Reviewed baseline

The independent report under `golive-deploy/p2-8c7806d-20261103/REPORT.html` validates commit `8c7806d597d2501289f1f9033117e97695c6925f` and its CI wheel (`dd52cdcde4b1f1feaa5645990da28bf43674c77f79eeacf925f0588315cf3dbf`). Its core editing/authorization checks passed, but it correctly withheld an unqualified green result:

- **UI01:** English pages displayed Chinese conflict titles, labels, buttons and confirmation. HTTP 409, retained drafts and unchanged stored content/snapshots were correct. This is a real usability defect.
- **H01–H03:** The installed full suite reported 1477 passed / 15 skipped / 3 failed. Tests looked for runtime Python files beside the copied test bundle, or build metadata beside site-packages. The matching source suite passed 1480 / 15. These are test resource-location defects, not three demonstrated runtime failures.

The original report and resources remain unchanged. Its counts are historical independent evidence, not results of the repaired package. Task-local copied report hashes and before/after logs are under `.artifacts/p2-ui01/` (ignored).

## Changes

The injected editor resolves visible controls, conflict/draft comparison, confirmation, loading and known conflict/error guidance in English or Chinese. Priority is an explicit saved admin preference (`golive_admin_lang=en|zh`), then the page's HTML language, then browser language; unsupported languages fall back to English. Restricted local storage falls back safely. Backend error details are retained; arbitrary server error strings are not translated. Language is browser-side, independent of server CLI locale. Re-publish legacy pages to update their injected editor script.

`tests/test_editor_i18n.py` executes the actual generated JavaScript in a small Node DOM fixture. Thirteen cases cover locale/preference/fallback, blocked storage, controls/labels/confirmation, read failure, missing revisions and draft retention. Actual-browser checks separately cover rendered English/Chinese and mobile layouts, real stale HTTP writes and unchanged content/snapshots.

Runtime module/resource assertions now locate the imported `golive` package. Project documentation/build declarations locate the matching sdist test bundle. Missing fixtures still fail; no assertion is replaced with a skip or dummy site-packages metadata. The outbound-probe scan also asserts it inspected real runtime source files, preventing an empty source tree from passing vacuously.

## Installed full-suite gate

The new CI `installed` job depends on the build artifacts, installs their exact wheel in a fresh venv, and runs `scripts/verify_installed.py` outside the checkout. The script verifies distribution hashes against the manifest, compares installed runtime files with the wheel and sdist, copies matching tests/metadata/static fixtures without any `golive/*.py`, verifies import provenance again from the test directory, isolates HOME/GOLIVE_HOME/XDG/TMPDIR, removes inherited Golive/Python configuration, and retains provenance/logs/JUnit results. It does not fabricate build metadata inside site-packages.

Repeat with a fresh venv containing the CI wheel plus pytest, pytest-timeout, Pillow and cryptography:

```bash
/path/to/venv/bin/python /path/to/scripts/verify_installed.py \
  --wheel /path/to/distributions/html_golive-0.9.8-py3-none-any.whl \
  --sdist /path/to/distributions/html_golive-0.9.8.tar.gz \
  --work-dir /new/empty-parent/installed-acceptance
```

The work directory itself must not already exist; files and test resources are retained. `artifact-manifest.json` must be next to the wheel. The default gate intentionally removes SQL test DSNs and runs the isolated non-live matrix; the existing dedicated PostgreSQL/MySQL/Supabase jobs retain real backend coverage.

Final fixed-commit results, artifact hashes and browser receipts are recorded in the PR and task-local validation receipt after execution. Source, installed and live-backend counts remain separate. External IdP exchange, real Supabase-specific group integration, independent-instance sharing and remote-storage conditional editing remain outside this repair's validation claims. No merge, release or production deployment is performed.
