# Data Layer — `window.TemplateAPI` / `window.SupabaseAPI`

golive can inject a JavaScript data layer into published pages, giving
static HTML full read/write persistence backed by your own Supabase
project. Pages built against the same API on other golive deployments
run **unchanged** — the API signatures are stable contracts.

## Setup (once)

1. Create a Supabase project (cloud or [self-hosted](https://supabase.com/docs/guides/self-hosting/docker)).
2. Print the schema and run it in the Supabase SQL Editor:

   ```bash
   golive db init --print-sql
   ```

3. Configure golive:

   ```yaml
   # golive.yaml
   supabase:
     url: https://YOURPROJECT.supabase.co
   data:
     backend: supabase
   ```

   ```bash
   export GOLIVE_SUPABASE_ANON_KEY=eyJ...        # used by injected JS
   export GOLIVE_SUPABASE_SERVICE_KEY=eyJ...     # used by CLI (optional)
   ```

4. Publish with a data model namespace:

   ```bash
   golive publish app.html --name MyApp --data-model myapp_v1
   ```

Pages calling `TemplateAPI.*` / `SupabaseAPI.*` are detected
automatically at publish time and get the matching layer injected. If no
data backend is configured, a **stub** is injected instead: the page
still publishes, and every data call rejects with a clear
configuration hint in the console.

> ⚠️ **RLS is mandatory.** The injected JS embeds your **anon key** —
> anyone viewing the page source can read it. Protect your tables with
> [Row Level Security](https://supabase.com/docs/guides/auth/row-level-security)
> policies. The SQL from `golive db init --print-sql` includes example
> policies to start from; tighten them before production use.

## `window.TemplateAPI`

Namespaced template/record store. Best for "each page owns its data"
apps: dashboards with saved views, form drafts, config panels.

| Method | Arguments | Resolves to |
|---|---|---|
| `list(opts)` | `{modelCode?, pageNo?, pageSize?, templateName?, userId?}` | `{total, list: Template[]}` (current user's rows) |
| `listAll(opts)` | same, `userId` ignored | `{total, list: Template[]}` (all users) |
| `get(templateId)` | id | `Template` |
| `create(tpl)` | `{modelCode?, name, content, desc?, version?}` | `templateId` |
| `update(templateId, patch)` | patch: `name/desc/content/version/modelCode` | `templateId` |
| `delete(templateId)` | id | `null` |
| `sort(templateId, sortIndex)` | — | `null` |
| `upsert(tpl)` | same as create; finds by exact `name` | `templateId` |
| `_config` | — | injected config (debug) |

`Template` rows carry: `templateId`, `templateName`, `templateDesc`,
`templateContent` (JSON string), `templateContentVersion`, `modelCode`,
`createTime`, `updateTime`.

### modelCode

A `modelCode` is a namespace inside the `golive_templates` table —
usually one per site. Multiple codes: `--data-model "a_v1,b_v1"`; then
pass `{modelCode: 'b_v1'}` in calls (default is the first one).

### Ready event

```html
<script>
document.addEventListener('templateapi:ready', function () {
  TemplateAPI.list({pageSize: 50}).then(r => render(r.list));
});
</script>
```

### Minimal example page

```html
<!DOCTYPE html>
<html><head><title>Notes</title></head>
<body>
  <input id="note"><button onclick="save()">Save</button>
  <ul id="list"></ul>
  <script>
    function refresh() {
      TemplateAPI.listAll({pageSize: 100}).then(r => {
        document.getElementById('list').innerHTML = r.list
          .map(t => '<li>' + t.templateName + ': '
               + JSON.parse(t.templateContent).text + '</li>').join('');
      });
    }
    function save() {
      var text = document.getElementById('note').value;
      TemplateAPI.upsert({name: 'note_' + Date.now(),
                          content: {text: text}}).then(refresh);
    }
    document.addEventListener('templateapi:ready', refresh);
  </script>
</body></html>
```

Publish: `golive publish notes.html --data-model notes_v1`.

## `window.SupabaseAPI`

Direct table access (PostgREST syntax) for pages that manage their own
tables. Create the tables yourself in Supabase, add RLS policies, then:

| Method | Arguments | Resolves to |
|---|---|---|
| `init()` | — | `user \| null` (auto-called on load) |
| `getUser()` | — | static identity or `null` |
| `isReady()` | — | `boolean` |
| `onReady(cb)` | callback | — |
| `logout()` | — | no-op (no OAuth broker in self-hosted mode) |
| `query(table, opts)` | `{select?, filters?, order?, limit?≤500, offset?≤10000}` | `{rows, count?}` |
| `insert(table, rows)` | row or array | `{rows}` incl. generated ids |
| `update(table, filters, values)` | filters: `{col: 'eq.v'}` | `{rows}` |
| `delete(table, filters)` | filters | `{rows}` |
| `_config` / `_request` | — | debug / advanced |

```js
SupabaseAPI.query('todos', {
  select: 'id,title,done',
  filters: {done: 'eq.false'},
  order: 'created_at.desc',
  limit: 50,
}).then(r => render(r.rows));

SupabaseAPI.insert('todos', [{title: 'hello'}]);
SupabaseAPI.update('todos', {id: 'eq.1'}, {done: true});
SupabaseAPI.delete('todos', {id: 'eq.1'});
```

## CLI twin — `golive data`

The same template store is scriptable server-side:

```bash
golive data list   --model-code myapp_v1
golive data upsert --model-code myapp_v1 --name cfg --content '{"k":1}'
golive data get    --id <uuid>
golive data delete --id <uuid>
```

## Migrating pages from another deployment

Pages built against a compatible TemplateAPI/SupabaseAPI (e.g. an
internal golive-like deployment) usually migrate by republishing:

```bash
golive migrate-check page.html     # report anything deployment-specific
golive publish page.html --data-model mymodel_v1
```

`migrate-check` reports hard-coded API hosts, leftover data-layer
script blocks (replaced automatically on republish), and data-layer
call statistics. See [migrate-from-intranet](migrate-from-intranet.md).
