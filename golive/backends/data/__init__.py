"""golive.backends.data — data-layer backends (TemplateAPI storage).

``sqlite`` (default): rows in ``$GOLIVE_HOME/data.db``; zero configuration.
``postgres``: rows in your own PostgreSQL, reached through ``$GOLIVE_PG_DSN``.
``supabase``: rows in a PostgREST table (``golive_templates``) in your project.
``none``: no data layer; pages calling TemplateAPI get a stub.

sqlite and postgres are *server-proxied* — published pages call the local
``/api/data`` endpoint and no credentials reach the browser. supabase is
*page-direct*: the page talks to your project with an anon key.
"""
