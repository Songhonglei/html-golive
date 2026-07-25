# Migrating pages from an intranet deployment

If your HTML pages were built on an internal golive-style deployment
(company-hosted publishing tool with `window.TemplateAPI` /
`window.SupabaseAPI`), they can run on the open-source stack **without
code changes** — the API signatures are identical. What changes is the
backend they talk to, and that is handled by republishing.

## Step 1 — check the page

```bash
golive migrate-check page.html
```

The report covers three categories, each with `file:line` and advice:

1. **Hard-coded intranet hosts** — internal API domains, CDN hosts,
   gateway paths. These must be replaced or removed; they are not
   reachable outside the company network.
2. **Leftover data-layer injections** — old
   `<script id="template-data-layer">` / `supabase-data-layer` blocks.
   No manual action needed: republishing replaces them automatically.
3. **Data-layer call statistics** — how many `TemplateAPI.*` /
   `SupabaseAPI.*` calls the page makes, and whether your open-source
   deployment has a data backend configured to serve them.

Exit code 0 = clean, 1 = items to handle.

## Step 2 — configure a data backend

Follow [data-layer.md](data-layer.md): create a Supabase project, run
`golive db init --print-sql` in its SQL editor, set `supabase.url` +
keys in `golive.yaml` / env.

## Step 3 — republish

```bash
golive publish page.html --name MyPage --data-model mymodel_v1
```

The old injected blocks are stripped and the open-source data layer is
injected in their place. `modelCode` values are preserved when present
(`--data-model` overrides).

## What does NOT carry over

- **Company SSO identities** — the OSS layer has no OAuth broker.
  `SupabaseAPI.getUser()` returns the statically configured identity
  (`data.supabase.user_id`) or `null`. Real auth providers land in M3.
- **Internal image CDN links** — re-run bundling (`golive publish` on
  the project directory) with an image uploader configured, or keep
  base64 inlining.
- **Internal BI / proxy layers** — out of scope for the OSS version.
