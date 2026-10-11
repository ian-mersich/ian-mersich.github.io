from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest import mock


TEMPLATE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("figure_pages_build_site", TEMPLATE / "scripts/build_site.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def zip_bytes(entries: list[tuple[str, bytes, int | None]] | None = None) -> bytes:
    entries = entries or [
        ("superbench/figure_tool/index.html", b"<h1>Figure Tool</h1>", None),
        ("superbench/figure_tool/app/index.html", b"<h1>Editor</h1>", None),
        ("superbench/figure_tool/LICENSE", b"Apache-2.0", None),
        ("superbench/figure_tool/NOTICE", b"Notices", None),
        ("superbench/figure_tool/app/main.js", b"console.log('ready')", None),
    ]
    import io
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
    return output.getvalue()


class FigurePagesConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.website = self.root / "website"
        self.pages = self.website / "pages"
        self.pages.mkdir(parents=True)
        (self.pages / "index.html").write_text("<main>site template</main>", encoding="utf-8")
        (self.pages / "superbench").mkdir()
        (self.pages / "superbench/index.html").write_text("<main>Superbench</main>", encoding="utf-8")
        self.license = self.root / "LICENSE"
        self.license.write_text("Apache License Version 2.0\n", encoding="utf-8")
        self.archive = self.root / "figure-tool-web.zip"
        self.archive.write_bytes(zip_bytes())
        self.config = self.root / "figure-release.json"
        self.write_config()

    def tearDown(self) -> None:
        shutil.rmtree(builder._fs(self.root), ignore_errors=True)
        self.temp.cleanup()

    def write_config(self, **changes: str) -> None:
        data = {
            "schema": "figurePagesRelease.v1",
            "product_version": "1.0.0-beta.6",
            "archive_url": builder.EXPECTED_URL,
            "archive_sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            "archive_root": builder.EXPECTED_PREFIX,
        }
        data.update(changes)
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def build(self, *, output: Path | None = None) -> Path:
        return builder.build_site(
            config_path=self.config,
            archive_path=self.archive,
            output_dir=output or (self.website / "_site"),
            pages_dir=self.pages,
            license_path=self.license,
            website_dir=self.website,
        )

    def test_build_assembles_only_expected_consumer_tree(self) -> None:
        output = self.build()
        expected = {
            "index.html", "superbench/index.html", "superbench/figure_tool/index.html",
            "superbench/figure_tool/app/index.html", "superbench/figure_tool/LICENSE",
            "superbench/figure_tool/NOTICE", "superbench/figure_tool/app/main.js",
            "LICENSE", ".nojekyll", "FIGURE_RELEASE.json",
        }
        actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
        self.assertEqual(actual, expected)
        self.assertEqual((output / "index.html").read_text(encoding="utf-8"), "<main>site template</main>")
        metadata = json.loads((output / "FIGURE_RELEASE.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["product_version"], "1.0.0-beta.6")
        self.assertEqual(metadata["archive_sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_real_template_is_neutral_and_links_only_the_two_products(self) -> None:
        root = (TEMPLATE / "pages/index.html").read_text(encoding="utf-8")
        overview = (TEMPLATE / "pages/superbench/index.html").read_text(encoding="utf-8")
        self.assertIn("/superbench/", root)
        self.assertIn("/superbench/figure_tool/", root)
        self.assertIn("/superbench/figure_tool/", overview)
        for forbidden in ("manuscript", "private report", "patient", "unpublished data", "personal research"):
            self.assertNotIn(forbidden, (root + overview).casefold())
        self.assertFalse((TEMPLATE / "CNAME").exists())
        self.assertTrue((TEMPLATE / "LICENSE").is_file())
        self.assertTrue((TEMPLATE / ".github/workflows/pages.yml").is_file())

    def test_pending_malformed_or_wrong_release_configuration_fails_closed(self) -> None:
        for field, value in (("archive_sha256", "PENDING"), ("archive_sha256", "a" * 63),
                             ("product_version", "1.0.0-beta.7"), ("archive_url", "https://example.com/latest.zip"),
                             ("archive_root", "figure_tool")):
            with self.subTest(field=field, value=value):
                self.write_config(**{field: value})
                with self.assertRaises(builder.BuildError):
                    self.build()

    def test_wrong_digest_and_existing_output_never_overwrite(self) -> None:
        self.write_config(archive_sha256="0" * 64)
        with self.assertRaisesRegex(builder.BuildError, "digest mismatch"):
            self.build()
        output = self.website / "already-there"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(builder.BuildError, "Refusing to overwrite"):
            self.build(output=output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_traversal_absolute_and_unexpected_top_level_paths_rejected(self) -> None:
        for name in ("superbench/figure_tool/../../escape.txt", "C:/outside.txt", "/absolute.txt",
                     "other/product.txt", "superbench\\..\\escape.txt"):
            with self.subTest(name=name):
                self.archive.write_bytes(zip_bytes([(name, b"x", None)] + [
                    ("superbench/figure_tool/index.html", b"x", None),
                    ("superbench/figure_tool/app/index.html", b"x", None),
                    ("superbench/figure_tool/LICENSE", b"x", None),
                    ("superbench/figure_tool/NOTICE", b"x", None),
                ]))
                self.write_config()
                with self.assertRaises(builder.BuildError):
                    self.build(output=self.website / ("out-" + str(abs(hash(name)))))

    def test_duplicate_case_collisions_symlinks_and_missing_required_files_rejected(self) -> None:
        required = zip_bytes()
        cases = [
            zip_bytes([( "superbench/figure_tool/index.html", b"a", None),
                       ("superbench/figure_tool/index.html", b"b", None)]),
            zip_bytes([( "superbench/figure_tool/index.html", b"a", None),
                       ("SUPERBENCH/FIGURE_TOOL/INDEX.HTML", b"b", None)]),
            zip_bytes([( "superbench/figure_tool/link", b"target", stat.S_IFLNK | 0o777),
                       ("superbench/figure_tool/index.html", b"a", None),
                       ("superbench/figure_tool/app/index.html", b"a", None),
                       ("superbench/figure_tool/LICENSE", b"a", None),
                       ("superbench/figure_tool/NOTICE", b"a", None)]),
            zip_bytes([( "superbench/figure_tool/index.html", b"a", None)]),
        ]
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                self.archive.write_bytes(content)
                self.write_config()
                with self.assertRaises(builder.BuildError):
                    self.build(output=self.website / f"reject-{index}")
        self.assertTrue(required)

    def test_parent_file_collision_and_size_ratio_limits_rejected(self) -> None:
        collision = zip_bytes([
            ("superbench/figure_tool/index.html", b"x", None),
            ("superbench/figure_tool/app/index.html", b"x", None),
            ("superbench/figure_tool/LICENSE", b"x", None),
            ("superbench/figure_tool/NOTICE", b"x", None),
            ("superbench/figure_tool/app", b"not a directory", None),
        ])
        self.archive.write_bytes(collision)
        self.write_config()
        with self.assertRaises(builder.BuildError):
            self.build(output=self.website / "collision")

        self.archive.write_bytes(zip_bytes([
            ("superbench/figure_tool/index.html", b"x" * 1024, None),
            ("superbench/figure_tool/app/index.html", b"x", None),
            ("superbench/figure_tool/LICENSE", b"x", None),
            ("superbench/figure_tool/NOTICE", b"x", None),
        ]))
        self.write_config()
        with mock.patch.object(builder, "MAX_COMPRESSION_RATIO", 10):
            with self.assertRaises(builder.BuildError):
                self.build(output=self.website / "ratio")

    def test_failed_build_cleans_temporary_stage_and_never_creates_output(self) -> None:
        self.write_config(archive_sha256="f" * 64)
        output = self.website / "_site"
        with self.assertRaises(builder.BuildError):
            self.build()
        self.assertFalse(output.exists())
        self.assertEqual(list(self.website.glob(".figure-pages-build-*")), [])

    def test_long_windows_stage_paths_extract_and_publish_nested_assets(self) -> None:
        asset = (
            "superbench/figure_tool/assets/scientific-packs/core-experimental-biology/"
            "svg/flow_cytometry_readout_histogram.svg"
        )
        expected_asset = b"<svg><title>long path extraction</title></svg>"
        self.archive.write_bytes(zip_bytes([
            ("superbench/figure_tool/index.html", b"<h1>Figure Tool</h1>", None),
            ("superbench/figure_tool/app/index.html", b"<h1>Editor</h1>", None),
            ("superbench/figure_tool/LICENSE", b"Apache-2.0", None),
            ("superbench/figure_tool/NOTICE", b"Notices", None),
            (asset, expected_asset, None),
        ]))
        self.write_config()
        long_website = self.root / ("release-" + "a" * 70) / ("site-" + "b" * 70) / "website"
        builder._fs(long_website).mkdir(parents=True)
        output = long_website / "_site"
        projected_target = long_website / ".figure-pages-build-12345678901234567890" / "site" / asset
        self.assertGreater(len(str(projected_target)), 260)
        builder.build_site(
            config_path=self.config,
            archive_path=self.archive,
            output_dir=output,
            pages_dir=self.pages,
            license_path=self.license,
            website_dir=long_website,
        )
        extracted = output.joinpath(*asset.split("/"))
        self.assertEqual(builder._fs(extracted).read_bytes(), expected_asset)
        self.assertTrue(builder._fs(output / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
