"""golive.backends.data — data-layer backends (TemplateAPI storage).

``none`` (default): no data layer; pages calling TemplateAPI get a stub.
``supabase``: templates stored in a PostgREST table (golive_templates).
"""
