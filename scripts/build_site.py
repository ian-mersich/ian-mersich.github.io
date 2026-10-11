#!/usr/bin/env python3
"""Build the small public Pages site from a digest-pinned Figure web release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT
PAGES = ROOT / "pages"
CONFIG = ROOT / "config" / "figure-release.json"
LICENSE = ROOT / "LICENSE"
EXPECTED_URL = (
    "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
    "v1.0.0-beta.6/figure-tool-web.zip"
)
EXPECTED_PREFIX = "superbench/figure_tool"
REQUIRED_FILES = {
    f"{EXPECTED_PREFIX}/index.html",
    f"{EXPECTED_PREFIX}/app/index.html",
    f"{EXPECTED_PREFIX}/LICENSE",
    f"{EXPECTED_PREFIX}/NOTICE",
}
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_ENTRIES = 50_000
MAX_FILE_BYTES = 500_000_000
MAX_TOTAL_BYTES = 2_000_000_000
MAX_COMPRESSION_RATIO = 1_000
ALLOWED_CUSTOM_DOMAIN = "imersich.com"


class BuildError(ValueError):
    """Input or archive is not safe to publish."""


def _fs(path: Path | str) -> Path:
    """Use Windows extended paths for filesystem calls; keep reports portable."""
    path = Path(path)
    if os.name != "nt":
        return path
    raw = os.path.abspath(os.fspath(path))
    if raw.startswith("\\\\?\\"):
        return Path(raw)
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw.lstrip("\\"))
    return Path("\\\\?\\" + raw)


def load_release_config(path: Path = CONFIG) -> dict[str, str]:
    try:
        data = json.loads(_fs(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read Figure release config: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "figurePagesRelease.v1":
        raise BuildError("Unsupported Figure Pages release config schema")
    if data.get("product_version") != "1.0.0-beta.6":
        raise BuildError("Pages consumer is pinned to Figure Tool 1.0.0-beta.6")
    if data.get("archive_url") != EXPECTED_URL or data.get("archive_root") != EXPECTED_PREFIX:
        raise BuildError("Figure release URL or archive root differs from the pinned beta.6 release")
    digest = data.get("archive_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BuildError("Figure release archive SHA-256 is pending or malformed")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _fs(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "figure-pages-consumer/1.0"})
    try:
        with urlopen(request, timeout=60) as response, _fs(destination).open("xb") as output:
            final_url = response.geturl()
            if urlsplit(final_url).scheme != "https":
                raise BuildError("Release download redirected to a non-HTTPS URL")
            total = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise BuildError("Figure release ZIP exceeds the download size limit")
                output.write(block)
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"Could not download pinned Figure release: {exc}") from exc


def _safe_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise BuildError("Figure ZIP is empty or has too many entries")
    seen: set[str] = set()
    files: set[str] = set()
    dirs: set[str] = set()
    total = 0
    result: list[tuple[zipfile.ZipInfo, str]] = []
    prefix = EXPECTED_PREFIX + "/"
    for info in infos:
        name = info.filename
        if not name or "\x00" in name or "\\" in name:
            raise BuildError(f"Unsafe ZIP member name: {name!r}")
        path = PurePosixPath(name)
        parts = name.rstrip("/").split("/")
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
        if (path.is_absolute() or any(part in {"", ".", ".."} for part in parts)
                or any(any(char in part for char in ':<>"|?*') or part.endswith((".", " "))
                       or part.split(".", 1)[0].upper() in reserved for part in parts)):
            raise BuildError(f"Unsafe ZIP member path: {name!r}")
        is_dir = info.is_dir()
        normalized = name.rstrip("/")
        key = normalized.casefold()
        if key in seen:
            raise BuildError(f"Duplicate or case-colliding ZIP member: {name}")
        seen.add(key)
        if not (normalized == EXPECTED_PREFIX or normalized.startswith(prefix)):
            raise BuildError(f"Unexpected path outside {EXPECTED_PREFIX}/: {name}")
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFDIR if is_dir else stat.S_IFREG):
            raise BuildError(f"ZIP member is a symlink or special file: {name}")
        if is_dir:
            dirs.add(key)
        else:
            files.add(key)
            if info.flag_bits & 0x1:
                raise BuildError(f"Encrypted ZIP member is unsupported: {name}")
            if info.file_size < 0 or info.file_size > MAX_FILE_BYTES:
                raise BuildError(f"ZIP member exceeds the per-file size limit: {name}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise BuildError("Figure ZIP exceeds the total uncompressed size limit")
            if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                raise BuildError(f"ZIP member exceeds the compression ratio limit: {name}")
        result.append((info, normalized))
    if files & dirs:
        raise BuildError("ZIP contains a path that is both a file and a directory")
    for filename in files:
        parts = filename.split("/")
        if any("/".join(parts[:count]) in files for count in range(1, len(parts))):
            raise BuildError(f"ZIP file is also a parent directory: {filename}")
    for filename in REQUIRED_FILES:
        if filename.casefold() not in files:
            raise BuildError(f"Figure ZIP is missing required file: {filename}")
    return result


def _extract_verified(archive_path: Path, destination: Path) -> None:
    if _fs(archive_path).stat().st_size > MAX_ARCHIVE_BYTES:
        raise BuildError("Figure release ZIP exceeds the archive size limit")
    try:
        with zipfile.ZipFile(_fs(archive_path)) as archive:
            members = _safe_members(archive)
            for info, name in members:
                target = _fs(destination.joinpath(*PurePosixPath(name).parts))
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                # ZipFile.open verifies CRC as the bytes are consumed.
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except BuildError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise BuildError(f"Cannot safely extract Figure release ZIP: {exc}") from exc


def _validated_cname(website_dir: Path) -> str | None:
    path = _fs(website_dir / "CNAME")
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise BuildError("CNAME must be a regular file in the site root")
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"Cannot read site CNAME: {exc}") from exc
    if value.strip() != ALLOWED_CUSTOM_DOMAIN or len(value.splitlines()) != 1:
        raise BuildError(f"CNAME must contain only the approved domain {ALLOWED_CUSTOM_DOMAIN}")
    return ALLOWED_CUSTOM_DOMAIN + "\n"


def build_site(
    *,
    config_path: Path = CONFIG,
    archive_path: Path | None = None,
    output_dir: Path | None = None,
    pages_dir: Path = PAGES,
    license_path: Path = LICENSE,
    website_dir: Path = WEBSITE,
) -> Path:
    config = load_release_config(config_path)
    output = output_dir or (website_dir / "_site")
    output = Path(output).resolve()
    website_abs = Path(website_dir).resolve()
    if output == website_abs or website_abs not in output.parents:
        raise BuildError("Output must be a child of the website directory")
    if _fs(output).exists():
        raise BuildError(f"Refusing to overwrite existing output: {output}")
    if not _fs(pages_dir).is_dir() or not _fs(license_path).is_file():
        raise BuildError("Website template pages or owner LICENSE are missing")
    cname_content = _validated_cname(Path(website_dir))
    _fs(output.parent).mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".figure-pages-build-", dir=_fs(website_abs)))
    try:
        archive = stage / "figure-tool-web.zip"
        if archive_path is None:
            _download(config["archive_url"], archive)
        else:
            source_archive = Path(archive_path)
            if _fs(source_archive).stat().st_size > MAX_ARCHIVE_BYTES:
                raise BuildError("Figure release ZIP exceeds the archive size limit")
            shutil.copyfile(_fs(source_archive), _fs(archive))
        actual_digest = _sha256(archive)
        if actual_digest != config["archive_sha256"]:
            raise BuildError(f"Figure ZIP digest mismatch: expected {config['archive_sha256']}, got {actual_digest}")

        site = stage / "site"
        shutil.copytree(_fs(pages_dir), _fs(site))
        _extract_verified(archive, site)
        shutil.copyfile(_fs(license_path), _fs(site / "LICENSE"))
        _fs(site / ".nojekyll").write_text("", encoding="utf-8")
        _fs(site / "FIGURE_RELEASE.json").write_text(
            json.dumps({"product_version": config["product_version"], "archive_sha256": actual_digest}, indent=2) + "\n",
            encoding="utf-8",
        )
        if cname_content is not None:
            _fs(site / "CNAME").write_text(cname_content, encoding="utf-8", newline="\n")
        # The staged subtree has the same root as the output, so rename is atomic on this volume.
        _fs(site).replace(_fs(output))
    except Exception:
        shutil.rmtree(_fs(stage), ignore_errors=True)
        raise
    shutil.rmtree(_fs(stage), ignore_errors=True)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a local release ZIP for offline qualification")
    parser.add_argument("--output", type=Path, help="Fresh output directory under publication/website/ (default: _site)")
    args = parser.parse_args(argv)
    try:
        output = build_site(archive_path=args.archive, output_dir=args.output)
    except BuildError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 2
    print(f"Built public Pages site at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
