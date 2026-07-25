"""golive.backends.images.s3 — native S3 uploader (coming in M2).

Planned config (golive.yaml)::

    uploader:
      s3:
        endpoint: https://s3.example.com
        bucket: golive-img
        prefix: img/
        access_key_env: GOLIVE_S3_AK
        secret_key_env: GOLIVE_S3_SK
        public_base: https://cdn.example.com

Until then, any S3-compatible store can already be used through
``CommandUploader`` with the AWS CLI, e.g.::

    export GOLIVE_UPLOADER_CMD='sh -c "aws s3 cp {file} s3://bucket/img/ >&2 && echo https://cdn.example.com/img/{name}"'
"""

from golive.backends.images.base import ImageUploader


class S3Uploader(ImageUploader):
    """Native S3 image uploader — implemented in M2."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "S3Uploader lands in M2. Meanwhile use CommandUploader "
            "(GOLIVE_UPLOADER_CMD) with the aws/mc CLI."
        )
