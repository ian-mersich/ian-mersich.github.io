#!/usr/bin/env python3
"""Build the public Pages site from digest-pinned scientific-tool releases."""
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
    "v1.0.0-beta.6-docs.1/figure-tool-web.zip"
)
EXPECTED_PREFIX = "superbench/figure_tool"
SHARED_RELEASE_URL = (
    "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
    "v1.0.0-beta.9/figure-tool-web.zip"
)
SHARED_RELEASE_URLS = {
    "1.0.0-beta.9": SHARED_RELEASE_URL,
    "1.0.0-beta.10": (
        "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
        "v1.0.0-beta.10/figure-tool-web.zip"
    ),
    "1.0.0-beta.11": (
        "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
        "v1.0.0-beta.11/figure-tool-web.zip"
    ),
    "1.0.0-beta.12": (
        "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
        "v1.0.0-beta.12/figure-tool-web.zip"
    ),
    "1.0.0-beta.13": (
        "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
        "v1.0.0-beta.13/figure-tool-web.zip"
    ),
    "1.0.0-beta.14": (
        "https://github.com/ian-mersich/superbench-figure-tool/releases/download/"
        "v1.0.0-beta.14/figure-tool-web.zip"
    ),
}
SHARED_PAYLOAD_ROOTS = ("app/", "vendor/", "assets/scientific-packs/",
                        "assets/scientific-scenes/", "web/")
SHARED_REQUIRED_FILES = {
    "app/index.html", "app/app.js", "app/styles.css", "web/index.html",
    "vendor/manifest.json", "assets/scientific-packs/library.json",
    "assets/scientific-scenes/library.v1.json", "app/legal/LICENSE", "app/legal/NOTICE",
}
MIRNA_DESTINATION = "superbench/mirna"
MIRNA_REQUIRED_FILES = {
    "index.html", "browser-worker.mjs", "browser-runtime.mjs",
    "data/model/manifest.json", "data/model/weights.bin", "release_manifest.json",
    "LICENSE", "NOTICE.txt", "MODEL_AND_RESULTS_LICENSE.md", "DATA_SOURCES.md",
    "RELEASE_METADATA.json",
}
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
    if not isinstance(data, dict) or data.get("schema") not in {"figurePagesRelease.v1", "figurePagesRelease.v2"}:
        raise BuildError("Unsupported Figure Pages release config schema")
    if data["schema"] == "figurePagesRelease.v1":
        if data.get("product_version") != "1.0.0-beta.6":
            raise BuildError("Pages consumer is pinned to Figure Tool 1.0.0-beta.6")
        if data.get("archive_url") != EXPECTED_URL or data.get("archive_root") != EXPECTED_PREFIX:
            raise BuildError("Figure release URL or archive root differs from the pinned beta.6 release")
    else:
        version = data.get("product_version")
        expected_url = SHARED_RELEASE_URLS.get(version) if isinstance(version, str) else None
        if (expected_url is None
                or data.get("archive_url") != expected_url
                or data.get("archive_root") != ""
                or data.get("destination") != EXPECTED_PREFIX):
            raise BuildError("Figure shared release layout or identity differs from a pinned reviewed release")
        for key in ("package_sha256", "payload_tree_sha256", "source_revision"):
            value = data.get(key)
            valid = isinstance(value, str) and (
                re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) if key == "source_revision"
                else re.fullmatch(r"[0-9a-f]{64}", value))
            if not valid:
                raise BuildError(f"Figure shared release {key} is missing or malformed")
    digest = data.get("archive_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BuildError("Figure release archive SHA-256 is pending or malformed")
    return data


def _mount_shared_figure(archive: Path, site: Path, config: dict[str, str]) -> None:
    """Mount the producer's unchanged web payload and verify desktop parity."""
    destination = site / EXPECTED_PREFIX
    _fs(destination).mkdir(parents=True, exist_ok=False)
    _extract_verified(archive, destination, archive_root="", required_files=SHARED_REQUIRED_FILES)
    inventory = []
    for path in sorted(_fs(destination).rglob("*"), key=lambda p: p.relative_to(_fs(destination)).as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(_fs(destination)).as_posix()
        if not relative.startswith(SHARED_PAYLOAD_ROOTS):
            raise BuildError(f"Figure file is outside the shared payload roots: {relative}")
        inventory.append((relative, _sha256(path)))
    tree = hashlib.sha256("".join(f"{name}\0{digest}\n" for name, digest in inventory).encode("utf-8")).hexdigest()
    if tree != config["payload_tree_sha256"]:
        raise BuildError("Figure web payload differs from the desktop release tree")
    # Hosting-only files sit outside all five payload roots. Never flatten web/
    # or rewrite app, assets or vendor files to create a second editor build.
    _fs(destination / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<title>Superbench Figure Tool</title><meta http-equiv="refresh" content="0;url=web/">'
        '<script>location.replace("web/"+location.search+location.hash)</script>'
        '<a href="web/">Open Figure Tool</a></html>\n', encoding="utf-8", newline="\n")
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(_fs(destination / "app/legal" / name), _fs(destination / name))
    _fs(destination / "SOURCE_RELEASE.json").write_text(json.dumps({
        "product_version": config["product_version"], "source_revision": config["source_revision"],
        "package_sha256": config["package_sha256"], "payload_tree_sha256": tree,
        "archive_sha256": config["archive_sha256"], "payload_file_count": len(inventory),
    }, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_mirna_release_config(path: Path) -> dict[str, str]:
    try:
        data = json.loads(_fs(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read miRNA release config: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "mirnaPagesRelease.v1":
        raise BuildError("Unsupported miRNA Pages release config schema")
    if data.get("publication_status") != "cleared":
        raise BuildError("miRNA release has not been cleared for publication")
    if data.get("destination") != MIRNA_DESTINATION or data.get("archive_root") != "":
        raise BuildError("miRNA ZIP must have a flat root and deploy only at superbench/mirna/")
    if data.get("model_id") != "s09_p1_browser_v1":
        raise BuildError("miRNA Pages consumer expects the accepted P1 browser model")
    version = data.get("product_version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise BuildError("miRNA product version is missing or malformed")
    url = data.get("archive_url")
    if not isinstance(url, str) or not re.fullmatch(
        r"https://github\.com/ian-mersich/[A-Za-z0-9._-]+/releases/download/"
        r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.zip", url
    ) or "/latest/" in url:
        raise BuildError("miRNA archive must use an immutable owner GitHub release URL")
    digest = data.get("archive_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BuildError("miRNA release archive SHA-256 is missing or malformed")
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


def _safe_members(
    archive: zipfile.ZipFile, *, archive_root: str = EXPECTED_PREFIX,
    required_files: set[str] = REQUIRED_FILES,
) -> list[tuple[zipfile.ZipInfo, str]]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise BuildError("Figure ZIP is empty or has too many entries")
    seen: set[str] = set()
    files: set[str] = set()
    dirs: set[str] = set()
    total = 0
    result: list[tuple[zipfile.ZipInfo, str]] = []
    prefix = archive_root + "/"
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
        if archive_root and not (normalized == archive_root or normalized.startswith(prefix)):
            raise BuildError(f"Unexpected path outside {archive_root}/: {name}")
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
    for filename in required_files:
        if filename.casefold() not in files:
            raise BuildError(f"Figure ZIP is missing required file: {filename}")
    return result


def _extract_verified(
    archive_path: Path, destination: Path, *, archive_root: str = EXPECTED_PREFIX,
    required_files: set[str] = REQUIRED_FILES,
) -> None:
    if _fs(archive_path).stat().st_size > MAX_ARCHIVE_BYTES:
        raise BuildError("Figure release ZIP exceeds the archive size limit")
    try:
        with zipfile.ZipFile(_fs(archive_path)) as archive:
            members = _safe_members(archive, archive_root=archive_root, required_files=required_files)
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
    mirna_config_path: Path | None = None,
    mirna_archive_path: Path | None = None,
) -> Path:
    config = load_release_config(config_path)
    mirna_path = mirna_config_path or (Path(website_dir) / "config/mirna-release.json")
    mirna_config = load_mirna_release_config(mirna_path) if mirna_config_path is not None or _fs(mirna_path).exists() else None
    if mirna_archive_path is not None and mirna_config is None:
        raise BuildError("A local miRNA archive requires a cleared pinned release config")
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
        if config["schema"] == "figurePagesRelease.v2":
            _mount_shared_figure(archive, site, config)
        else:
            _extract_verified(archive, site)
        if mirna_config is not None:
            mirna_archive = stage / "mirna-predictor-web.zip"
            if mirna_archive_path is None:
                _download(mirna_config["archive_url"], mirna_archive)
            else:
                if _fs(mirna_archive_path).stat().st_size > MAX_ARCHIVE_BYTES:
                    raise BuildError("miRNA release ZIP exceeds the archive size limit")
                shutil.copyfile(_fs(mirna_archive_path), _fs(mirna_archive))
            mirna_digest = _sha256(mirna_archive)
            if mirna_digest != mirna_config["archive_sha256"]:
                raise BuildError("miRNA ZIP digest differs from its accepted release pin")
            mirna_output = site / MIRNA_DESTINATION
            _fs(mirna_output).mkdir(parents=True, exist_ok=False)
            _extract_verified(
                mirna_archive, mirna_output, archive_root="",
                required_files=MIRNA_REQUIRED_FILES,
            )
            try:
                manifest_bytes = _fs(mirna_output / "release_manifest.json").read_bytes()
                tool_manifest = json.loads(manifest_bytes)
                tool_metadata = json.loads(_fs(mirna_output / "RELEASE_METADATA.json").read_text(encoding="utf-8"))
                if (tool_manifest.get("publication_status") != "cleared"
                        or tool_metadata.get("publication_status") != "cleared"
                        or tool_manifest.get("release_version") != mirna_config["product_version"]
                        or tool_metadata.get("release_version") != mirna_config["product_version"]
                        or tool_manifest.get("model", {}).get("id") != mirna_config["model_id"]
                        or tool_metadata.get("model_id") != mirna_config["model_id"]):
                    raise BuildError("miRNA artifact identity or clearance differs from its release pin")
                expected_manifest = mirna_config.get("release_manifest_sha256")
                if expected_manifest and hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest:
                    raise BuildError("miRNA release manifest differs from its accepted pin")
            except (OSError, UnicodeError, ValueError, AttributeError) as exc:
                raise BuildError(f"Cannot verify miRNA artifact metadata: {exc}") from exc
            _fs(site / "MIRNA_RELEASE.json").write_text(
                json.dumps({key: mirna_config[key] for key in (
                    "product_version", "model_id", "archive_sha256",
                )}, indent=2) + "\n", encoding="utf-8",
            )
        shutil.copyfile(_fs(license_path), _fs(site / "LICENSE"))
        _fs(site / ".nojekyll").write_text("", encoding="utf-8")
        release_metadata = {"product_version": config["product_version"], "archive_sha256": actual_digest}
        if config["schema"] == "figurePagesRelease.v2":
            release_metadata.update({key: config[key] for key in ("source_revision", "package_sha256", "payload_tree_sha256")})
        _fs(site / "FIGURE_RELEASE.json").write_text(
            json.dumps(release_metadata, indent=2) + "\n",
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
    parser.add_argument("--mirna-config", type=Path, help="Explicit cleared miRNA release config")
    parser.add_argument("--mirna-archive", type=Path, help="Use a local pinned miRNA ZIP for offline qualification")
    parser.add_argument("--output", type=Path, help="Fresh output directory under the website checkout (default: _site)")
    args = parser.parse_args(argv)
    try:
        output = build_site(
            archive_path=args.archive, output_dir=args.output,
            mirna_config_path=args.mirna_config, mirna_archive_path=args.mirna_archive,
        )
    except BuildError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 2
    print(f"Built public Pages site at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
