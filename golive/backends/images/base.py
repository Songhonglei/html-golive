"""golive.backends.images.base — ImageUploader interface.

An ImageUploader turns raw image bytes into a public URL. When no
uploader is configured, golive inlines images as base64 data URIs.

Contract:
  upload(data, filename) MUST return an http(s) URL on success and
  MUST raise UploadError (or any Exception) on failure — callers treat
  any exception as "fall back to base64 inlining", so a failed upload
  never breaks a publish.
"""



from __future__ import annotations
class UploadError(RuntimeError):
    """Raised when an image upload fails (caller falls back to base64)."""


class ImageUploader:
    """Interface for image-upload backends."""

    def upload(self, data: bytes, filename: str) -> str:
        """Upload image bytes; return the public URL.

        Args:
          data:     raw image bytes.
          filename: original filename (used for the upload's name/suffix).

        Returns:
          A public ``http(s)://`` URL referencing the uploaded image.

        Raises:
          UploadError: when the upload fails.
        """
        raise NotImplementedError
