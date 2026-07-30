# Contributing to html-golive

Thanks for taking the time to contribute! This project is small, so the
process is deliberately lightweight.

## Getting set up

```bash
git clone https://github.com/Songhonglei/html-golive.git
cd html-golive
pip install -e '.[image,dev]'
python -m pytest tests/ -q          # 232 tests, should be all green
```

Everything runs on the Python standard library by default — no database
or cloud account is needed for local development. Optional extras pull
in Pillow (`image`) and boto3 (`s3`).

Try the tool against itself:

```bash
export GOLIVE_HOME=/tmp/golive-dev
golive publish README.md --slug dev-test   # or any .html file
golive serve                               # visit /admin
```

## Making a change

1. **Open an issue first** for anything beyond a typo fix — it saves you
   from writing code that doesn't fit the design.
2. Keep the change focused. One concern per pull request.
3. **Add tests.** Every behaviour change needs a test that fails before
   your fix and passes after it. See `tests/` for the existing patterns
   — `tests/fake_postgrest.py` gives you a real HTTP data backend to
   test against without any cloud dependency.
4. Run the full suite before pushing: `python -m pytest tests/ -q`.
5. CI runs the suite on Python 3.9, 3.11 and 3.12 plus a wheel build and
   an install-from-wheel smoke test. All four jobs must be green.

## Code conventions

- **Python 3.9 compatible.** Every module starts with
  `from __future__ import annotations` so modern type syntax works on
  older interpreters. CI will catch you if you forget.
- **No new runtime dependencies** without discussion. The core install
  is stdlib-only on purpose — it's what makes `pip install html-golive`
  work anywhere, including airgapped hosts.
- **Escape everything you inject.** Values that end up inside a
  `<script>` block go through `golive/inject/_escape.py`
  (`json_for_script` / `safe_comment`); values rendered into the admin
  portal go through the front-end `esc()` helper. There are tests that
  fire XSS payloads at both paths.
- **Fail open on telemetry, fail closed on permissions.** Audit-log
  writes must never break a request; permission checks must run before
  anything else (403 before 400).
- Keep the admin portal self-contained — no external CDN, no frontend
  framework. It has to work on a machine with no internet access.

## Reporting bugs

Include the golive version (`golive --version` or `pip show
html-golive`), your Python version, which backends you configured
(local / Supabase / S3), and what you expected versus what happened.
Redact tokens and internal hostnames before pasting logs.

## Security issues

Please don't open a public issue for a vulnerability. Email the
maintainer or use GitHub's private security advisory feature instead.

## License

By contributing you agree that your contributions are licensed under the
MIT License, same as the rest of the project.
