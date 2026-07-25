"""M3 tests for the two M2 leftover WARN fixes:
1. S3 error matching via botocore's official Error.Code API
2. Supabase Storage prune advisory lock
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_m2fix_"))


class _FakeClientError(Exception):
    """Shape-compatible with botocore.exceptions.ClientError."""

    def __init__(self, code, message="err"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class TestS3ErrorCodes(unittest.TestCase):
    def test_code_extraction(self):
        from golive.backends.storage.s3 import _client_error_code
        self.assertEqual(_client_error_code(_FakeClientError("NoSuchKey")),
                         "NoSuchKey")
        self.assertEqual(_client_error_code(ValueError("nope")), "")

    def _storage_with_mock(self, error):
        from golive.backends.storage.s3 import S3Storage
        st = S3Storage.__new__(S3Storage)   # skip boto3 init
        st.bucket = "b"
        st.prefix = ""
        st.public_base = ""
        st._cache = {}
        client = mock.Mock()
        # exceptions.NoSuchKey must be a real exception type that does NOT
        # match our fake error, to exercise the generic branch
        client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        client.get_object.side_effect = error
        st.s3 = client
        return st

    def test_not_found_codes_map_to_filenotfound(self):
        for code in ("NoSuchKey", "404", "NotFound", "NoSuchBucket"):
            st = self._storage_with_mock(_FakeClientError(code))
            with self.assertRaises(FileNotFoundError):
                st.read("site1", use_cache=False)

    def test_access_denied_maps_to_permissionerror(self):
        st = self._storage_with_mock(_FakeClientError("AccessDenied"))
        with self.assertRaises(PermissionError):
            st.read("site1", use_cache=False)

    def test_other_codes_reraise(self):
        st = self._storage_with_mock(_FakeClientError("SlowDown"))
        with self.assertRaises(_FakeClientError):
            st.read("site1", use_cache=False)

    def test_message_text_no_longer_fools_matching(self):
        """v0.2 bug: any error whose *message* contained '404' was swallowed
        as FileNotFoundError. Now only the official code matters."""
        st = self._storage_with_mock(
            _FakeClientError("InternalError", message="backend at pool-404 died"))
        with self.assertRaises(_FakeClientError):
            st.read("site1", use_cache=False)


class TestSupabasePruneLock(unittest.TestCase):
    def _storage(self):
        from golive.backends.storage.supabase_store import SupabaseStorage
        st = SupabaseStorage.__new__(SupabaseStorage)
        st.base = "https://fake.supabase.co"
        st.key = "k"
        st.bucket = "b"
        st._cache = {}
        return st

    def test_lock_acquired_when_absent(self):
        st = self._storage()
        with mock.patch.object(st, "_download", return_value=None), \
             mock.patch("golive.backends.storage.supabase_store.requests.post") as post:
            post.return_value = mock.Mock(status_code=200)
            self.assertTrue(st._try_acquire_prune_lock("site1"))
            # lock payload carries pid + ts
            body = json.loads(post.call_args.kwargs["data"].decode())
            self.assertIn("pid", body)
            self.assertIn("ts", body)

    def test_fresh_lock_blocks(self):
        import time
        st = self._storage()
        fresh = json.dumps({"pid": 1, "ts": time.time()})
        with mock.patch.object(st, "_download", return_value=fresh):
            self.assertFalse(st._try_acquire_prune_lock("site1"))

    def test_stale_lock_taken_over(self):
        import time
        st = self._storage()
        stale = json.dumps({"pid": 1, "ts": time.time() - 120})
        with mock.patch.object(st, "_download", return_value=stale), \
             mock.patch("golive.backends.storage.supabase_store.requests.post") as post:
            post.return_value = mock.Mock(status_code=200)
            self.assertTrue(st._try_acquire_prune_lock("site1"))

    def test_corrupt_lock_treated_as_stale(self):
        st = self._storage()
        with mock.patch.object(st, "_download", return_value="not-json{"), \
             mock.patch("golive.backends.storage.supabase_store.requests.post") as post:
            post.return_value = mock.Mock(status_code=200)
            self.assertTrue(st._try_acquire_prune_lock("site1"))

    def test_prune_skipped_when_lock_held(self):
        import time
        st = self._storage()
        fresh = json.dumps({"pid": 1, "ts": time.time()})
        with mock.patch.object(st, "_download", return_value=fresh), \
             mock.patch.object(st, "list_snapshots") as ls:
            st._prune("site1")
            ls.assert_not_called()   # skipped entirely

    def test_prune_deletes_and_releases_lock(self):
        st = self._storage()
        snaps = [{"ts": f"2026010{i}_000000_000000", "path": f"p{i}"}
                 for i in range(12)]
        removed = []
        with mock.patch.object(st, "_try_acquire_prune_lock", return_value=True), \
             mock.patch.object(st, "list_snapshots", return_value=snaps), \
             mock.patch.object(st, "_remove", side_effect=removed.append), \
             mock.patch.object(st, "_release_prune_lock") as rel:
            st._prune("site1")
            self.assertEqual(len(removed), 2)   # 12 -> keep 10
            rel.assert_called_once_with("site1")


if __name__ == "__main__":
    unittest.main()
