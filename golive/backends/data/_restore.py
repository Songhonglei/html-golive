"""Internal archive restore contract; ordinary CRUD keeps generating IDs."""
from __future__ import annotations

import datetime
import json

FIELDS = ("id", "model_code", "name", "user_id", "description", "content",
          "version", "sort_index", "created_at", "updated_at")


class RestoreConflict(ValueError):
    """An existing target record cannot be changed without losing identity."""


class RestoreMismatch(RuntimeError):
    """Write/readback did not satisfy the archive contract."""


def restore_payload(row):
    """Validate before writing; older archives may omit optional metadata."""
    if not isinstance(row, dict) or set(row) - set(FIELDS):
        raise ValueError("Unsupported data record fields in archive")
    for key in ("id", "model_code", "name"):
        if not isinstance(row.get(key), str) or (key == "id" and not row[key]):
            raise ValueError("Archive data record needs string id/model_code/name")
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    result = dict(user_id="", description="", content={}, version="1.0.0",
                  sort_index=0, created_at=now, updated_at=row.get("created_at", now))
    result.update(row)
    for key in ("user_id", "description", "version", "created_at", "updated_at"):
        if not isinstance(result[key], str):
            raise ValueError("Archive data metadata must be strings")
    for key in ("created_at", "updated_at"):
        try:
            datetime.datetime.fromisoformat(result[key].replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Archive data timestamp is invalid") from None
    if type(result["sort_index"]) is not int:
        raise ValueError("Archive data sort_index must be an integer")
    # Preserve JSON scalars as well as objects; CRUD's _jsonify is not a
    # restore operation (it interprets string values and normalizes null).
    json.dumps(result["content"], allow_nan=False)
    return {key: result[key] for key in FIELDS}


def restore_sql_row(store, row, overwrite=False, placeholder="%s"):
    payload = restore_payload(row)
    values = dict(payload, content=json.dumps(payload["content"], ensure_ascii=False,
                                             allow_nan=False))
    with store._conn() as connection:
        updated = False
        if overwrite:
            columns = FIELDS[1:]
            cursor = connection.execute(
                f"UPDATE {store.table} SET " + ", ".join(f"{k} = {placeholder}" for k in columns)
                + f" WHERE id = {placeholder}",
                [values[k] for k in columns] + [payload["id"]])
            updated = cursor.rowcount > 0
        if not updated:
            connection.execute(
                f"INSERT INTO {store.table} ({', '.join(FIELDS)}) VALUES "
                f"({', '.join([placeholder] * len(FIELDS))})",
                [values[k] for k in FIELDS])
        connection.commit()
    restored = store.get(payload["id"])
    if restored is None:
        raise RuntimeError("Restored data record is not readable")
    return restored


def same_record(expected, actual):
    """PostgREST normalizes timestamptz formatting; compare the instants."""
    if actual is None:
        return False
    for key in FIELDS:
        left, right = expected.get(key), actual.get(key)
        if key in ("created_at", "updated_at"):
            try:
                left = datetime.datetime.fromisoformat(left.replace("Z", "+00:00"))
                right = datetime.datetime.fromisoformat(right.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                return False
        if left != right:
            return False
    return True
