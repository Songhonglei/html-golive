# Quickstart

## Zero-config single machine (v0.1)

```bash
pip install git+https://github.com/Songhonglei/html-golive.git   # PyPI release coming soon

golive publish index.html --name Demo --slug demo
golive serve --port 8787
# → http://<host>:8787/demo
```

Data lives in `~/.golive/` (override with `GOLIVE_HOME`).

## Common flows

### Publish a project folder

```bash
golive publish ./my-dashboard/ --slug dash --style minimal --compress
```

All CSS/JS/images are inlined into a single HTML file. Framework projects
(React/Vue/...) must be built first — publish the `dist/` folder.

### Update & rollback

```bash
golive publish v2.html --update dash     # keeps the same URL
golive rollback dash --dry-run           # list snapshots (max 10 kept)
golive rollback dash --yes               # restore the latest snapshot
```

### Clone a public page

```bash
golive clone https://example.com --save-only     # save locally, review, then publish
golive clone https://spa.example.com --headless  # JS-rendered pages need Chrome
```

### Protect the API

```bash
export GOLIVE_TOKEN=$(openssl rand -hex 24)
golive serve
# /api/sites now requires:  Authorization: Bearer $GOLIVE_TOKEN
```

## Supabase / S3 paths

Coming in M2 — see the Roadmap in the main README and the placeholder
fields in `golive.example.yaml`.
