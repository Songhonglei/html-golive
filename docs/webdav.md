# WebDAV page storage (P3)

For users with a NAS, Nextcloud or company WebDAV service, pages and their HTML
snapshots can live in an existing dedicated collection. OpenGoLive continues to
serve the pages through its own HTTP server; the NAS does not need to host HTML
publicly. Database rows, registry, sessions, image uploads and full-instance
backup remain separate concerns.

```yaml
storage:
  backend: webdav
  webdav:
    url: https://nas.example/remote.php/dav/files/golive/sites/
    username_env: GOLIVE_WEBDAV_USERNAME
    password_env: GOLIVE_WEBDAV_PASSWORD
    timeout: 15
```

Pre-create the collection and use a dedicated account restricted to it. Put
credentials in the server environment, never YAML/HTML; extra dependencies are
not required. Use the canonical collection URL: redirects are refused, including
same-origin redirects, to avoid credential forwarding and ambiguous writes.
TLS verification uses Requests' normal CA handling; a private CA can use
`REQUESTS_CA_BUNDLE`. HTTPS is required except literal loopback HTTP for local
fixtures. URL userinfo, query secrets and traversal segments are rejected.

Layout: `<site_id>/index.html` and `<site_id>/backups/<UTC timestamp>.html`.
The adapter uses MKCOL, GET/HEAD, PUT, Depth:1 PROPFIND and DELETE, following
[RFC 4918](https://www.rfc-editor.org/rfc/rfc4918.html). It retains ten snapshots
and supports selecting a snapshot for rollback. Delete is restricted to a
validated site collection. It never deletes the configured root or follows
foreign/traversal snapshot hrefs. A partial (207) delete is an error, not success.

Credentials and private collection URLs never become a public CDN URL; pages
must be accessed through OpenGoLive. There is no process-local content cache,
so reads observe committed remote changes. Connect/read timeouts are configured
in seconds (>0, <=120); response bodies are limited to 16 MiB. Remote response
bodies and underlying connection exceptions are not exposed in adapter errors.
401/403, missing files, timeout/TLS and storage/server failures stay distinct.

Remote editor conditional writes currently return **501**, as with other remote
page stores. WebDAV may support ETags/locks, but this adapter does not claim the
cross-request snapshot-and-replace atomicity required by P2. Unconditional
CLI publish/rollback are single-writer operations; coordinate writers externally.
Failure after a remote write may leave an indeterminate result: read and compare
before retrying. A failed snapshot read prevents overwriting the current page.

`doctor --json` reports the configured hostname and says the connection was not
probed; it does not imply NAS reachability. Contract/failure tests use isolated
HTTP resources. A specific NAS/Nextcloud version, external TLS/enterprise proxy
and production performance need target-specific acceptance. See
[P3 validation](validation-p3.md).
