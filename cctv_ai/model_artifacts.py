from __future__ import annotations

import hashlib
import os
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_matches_sha256(path: Path, expected_sha256: str) -> bool:
    try:
        return path.is_file() and sha256_file(path).lower() == expected_sha256.lower()
    except OSError:
        return False


def download_verified_https(
    url: str,
    target: Path,
    *,
    expected_sha256: str,
    max_bytes: int,
    timeout_seconds: float = 120.0,
) -> Path:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Model download URL must be HTTPS without embedded credentials")

    if file_matches_sha256(target, expected_sha256):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.download")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "CCTV-Processor/1.0"})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            final_url = urlsplit(response.geturl())
            if final_url.scheme.lower() != "https":
                raise ValueError("Model download redirected to a non-HTTPS URL")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("Model download exceeds the configured size limit")
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Model download exceeds the configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise ValueError("Downloaded model archive failed SHA-256 validation")
        temporary.replace(target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def safe_extract_zip(
    archive_path: Path,
    destination: Path,
    *,
    max_members: int,
    max_uncompressed_bytes: int,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError("Model archive contains too many entries")
        declared_total = sum(max(0, item.file_size) for item in members)
        if declared_total > max_uncompressed_bytes:
            raise ValueError("Model archive exceeds the uncompressed size limit")

        extracted_total = 0
        for item in members:
            relative = PurePosixPath(item.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Model archive contains an unsafe path")
            if relative.parts and ":" in relative.parts[0]:
                raise ValueError("Model archive contains an unsafe drive path")
            mode = (item.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError("Model archive contains a symbolic link")

            target = (root / Path(*relative.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError("Model archive entry escapes the target directory") from exc
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item, "r") as source, target.open("wb") as output:
                while True:
                    chunk = source.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    extracted_total += len(chunk)
                    if extracted_total > max_uncompressed_bytes:
                        raise ValueError("Model archive exceeds the extraction size limit")
                    output.write(chunk)
