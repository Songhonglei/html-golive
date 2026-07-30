# Quickstart

## Zero-config single machine (v0.1)

```bash
pip install html-golive        # + 'html-golive[image]' for image compression

golive publish index.html --name Demo --slug demo
golive serve --port 8787
# → http://<host>:8787/demo
```

Data lives in `~/.golive/` (override with `GOLIVE_HOME`): published
HTML, the SQLite registry, and the SQLite data layer. Nothing external
to register.

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

### Publish a page with data

```bash
golive publish app.html --slug app --data-model app_v1
golive serve
```

Pages calling `window.TemplateAPI` get the data layer injected
automatically. The default `sqlite` backend stores rows in
`$GOLIVE_HOME/data.db` and serves them at `/api/data` — so open the page
through `golive serve`, not as a local file. Details:
[data-layer.md](data-layer.md).

### Teach your AI agent to use golive

```bash
golive skill install       # auto-detects the agent's skills directory
golive skill status        # check it matches the installed golive
```

### Protect the API

```bash
export GOLIVE_TOKEN=$(openssl rand -hex 24)
golive serve
# /api/sites now requires:  Authorization: Bearer $GOLIVE_TOKEN
```

## Supabase / S3 paths

Each of the three backend layers switches independently in
`golive.yaml`; the defaults (`local` storage, `sqlite` registry,
`sqlite` data) need no configuration at all.

```yaml
# golive.yaml — one Supabase project behind all three layers
supabase:
  url: https://YOURPROJECT.supabase.co
storage:  { backend: supabase }
registry: { backend: supabase }
data:     { backend: supabase }
```

```bash
export GOLIVE_SUPABASE_SERVICE_KEY=eyJ...   # CLI / serve
export GOLIVE_SUPABASE_ANON_KEY=eyJ...      # embedded in injected page JS
golive db init --print-sql                  # run the SQL in Supabase
```

S3-compatible object storage (MinIO / OSS / COS / S3) works the same way
via `storage.backend: s3` with `pip install 'html-golive[s3]'`.

Configuration matrix and worked combinations:
[backends.md](backends.md).
