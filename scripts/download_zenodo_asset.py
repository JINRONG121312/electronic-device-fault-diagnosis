"""Resumable, range-based downloader for large public Zenodo assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and verify a Zenodo asset.")
    parser.add_argument("url")
    parser.add_argument("output_path")
    parser.add_argument("--md5", required=True, help="Expected MD5 without the md5: prefix.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-mib", type=int, default=16)
    args = parser.parse_args()

    output = Path(args.output_path)
    expected_md5 = args.md5.casefold().removeprefix("md5:")
    if output.is_file() and md5_file(output) == expected_md5:
        print(f"Verified existing {output.name}")
        return 0

    total_size = remote_size(args.url)
    chunk_size = args.chunk_mib * 1024 * 1024
    chunks = [(start, min(start + chunk_size - 1, total_size - 1)) for start in range(0, total_size, chunk_size)]
    temporary = output.with_name(f"{output.name}.part")
    progress_path = output.with_name(f"{output.name}.progress.json")
    completed = initialize_resume_state(temporary, progress_path, args.url, total_size, len(chunks))
    write_lock = threading.Lock()

    pending = [(index, start, end) for index, (start, end) in enumerate(chunks) if index not in completed]
    print(f"Downloading {output.name}: {len(completed)}/{len(chunks)} chunks already complete")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(download_chunk, args.url, temporary, start, end): (index, start, end)
            for index, start, end in pending
        }
        for future in as_completed(futures):
            index, _, _ = futures[future]
            future.result()
            with write_lock:
                completed.add(index)
                write_progress(progress_path, args.url, total_size, completed)
                print(f"Completed {len(completed)}/{len(chunks)} chunks")

    actual_md5 = md5_file(temporary)
    if actual_md5 != expected_md5:
        raise RuntimeError(f"MD5 mismatch for {output.name}: expected {expected_md5}, got {actual_md5}")
    os.replace(temporary, output)
    progress_path.unlink(missing_ok=True)
    print(f"Verified {output.name}")
    return 0


def remote_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        value = response.headers.get("Content-Length")
    if not value or not value.isdigit():
        raise RuntimeError("remote server did not provide Content-Length")
    return int(value)


def initialize_resume_state(
    temporary: Path,
    progress_path: Path,
    url: str,
    total_size: int,
    chunk_count: int,
) -> set[int]:
    completed: set[int] = set()
    if progress_path.is_file():
        try:
            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            if saved.get("url") == url and saved.get("total_size") == total_size and temporary.is_file():
                completed = {int(index) for index in saved.get("completed_chunks", []) if 0 <= int(index) < chunk_count}
        except (OSError, ValueError, json.JSONDecodeError):
            completed = set()
    if not completed:
        progress_path.unlink(missing_ok=True)
        with temporary.open("wb") as handle:
            handle.truncate(total_size)
    elif temporary.stat().st_size != total_size:
        completed = set()
        with temporary.open("wb") as handle:
            handle.truncate(total_size)
    return completed


def download_chunk(url: str, temporary: Path, start: int, end: int) -> None:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(request, timeout=180) as response:
        status = getattr(response, "status", response.getcode())
        if status != 206:
            raise RuntimeError(f"server ignored Range request {start}-{end}; HTTP {status}")
        payload = response.read()
    expected_size = end - start + 1
    if len(payload) != expected_size:
        raise RuntimeError(f"incomplete range {start}-{end}: expected {expected_size}, got {len(payload)}")
    with temporary.open("r+b") as handle:
        handle.seek(start)
        handle.write(payload)


def write_progress(progress_path: Path, url: str, total_size: int, completed: set[int]) -> None:
    content = {
        "url": url,
        "total_size": total_size,
        "completed_chunks": sorted(completed),
    }
    progress_path.write_text(json.dumps(content, sort_keys=True), encoding="utf-8")


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
