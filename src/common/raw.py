"""Raw S3 writer. Every run writes new objects named after the run and never overwrites, so raw data
stays immutable; the transform reads only what it needs from the duplicates overlapping runs
create (D19, D23)."""

import gzip
import io
import json
from datetime import date


def key(source: str, kind: str, day: date, run: str, ext: str = "jsonl") -> str:
    return f"raw/{source}/{kind}/dt={day}/run={run}.{ext}.gz"


class Writer:
    """Streams API pages into one gzipped JSON Lines object, one page per line, so memory holds
    the compressed bytes rather than the parsed pages (gzip shrinks this data about 50x).
    Used with `with`: uploads only if the block finishes without an error and some page had
    records (`has_data`), so failed or empty fetches leave nothing behind."""

    def __init__(self, s3, bucket: str, key: str):
        self.s3, self.bucket, self.key, self.has_data = s3, bucket, key, False
        self.buf = io.BytesIO()
        self.gz = gzip.GzipFile(fileobj=self.buf, mode="wb")

    def write(self, page: dict, records: int) -> None:
        self.gz.write(json.dumps(page).encode() + b"\n")
        self.has_data = self.has_data or records > 0

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, exc_type, *_) -> None:  # exc_type is None when the block succeeded
        self.gz.close()
        if exc_type is None and self.has_data:
            self.s3.put_object(Bucket=self.bucket, Key=self.key, Body=self.buf.getvalue())
