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

    def shared_release(self, extra: list[tuple[str, bytes, int | None]] | None = None,
                       *, version: str = "1.0.0-beta.9") -> dict[str, bytes]:
        entries = [(name, (name + " exact shared bytes").encode(), None)
                   for name in sorted(builder.SHARED_REQUIRED_FILES)]
        entries += extra or []
        self.archive.write_bytes(zip_bytes(entries))
        ordered = sorted(entries, key=lambda row: row[0].casefold())
        tree = hashlib.sha256("".join(f"{name}\0{hashlib.sha256(content).hexdigest()}\n"
                                     for name, content, _ in ordered).encode()).hexdigest()
        self.write_config(schema="figurePagesRelease.v2", product_version=version,
                          archive_url=builder.SHARED_RELEASE_URLS[version], archive_root="",
                          destination=builder.EXPECTED_PREFIX, source_revision="a" * 40,
                          package_sha256="b" * 64, payload_tree_sha256=tree)
        return {name: content for name, content, _ in entries}

    def test_shared_release_mounts_every_payload_byte_and_retains_release_identity(self) -> None:
        expected = self.shared_release([("assets/scientific-packs/family/old.svg", b"<svg/>", None)])
        output = self.build()
        tool = output / builder.EXPECTED_PREFIX
        for name, content in expected.items():
            self.assertEqual((tool / name).read_bytes(), content)
        self.assertIn('location.replace("web/"+location.search+location.hash)', (tool / "index.html").read_text())
        self.assertEqual((tool / "LICENSE").read_bytes(), expected["app/legal/LICENSE"])
        metadata = json.loads((tool / "SOURCE_RELEASE.json").read_text())
        self.assertEqual(metadata["package_sha256"], "b" * 64)
        self.assertEqual(metadata["source_revision"], "a" * 40)
        self.assertEqual(metadata["payload_file_count"], len(expected))
        self.assertEqual(json.loads((output / "FIGURE_RELEASE.json").read_text())["package_sha256"], "b" * 64)

    def test_reviewed_shared_releases_preserve_every_payload_byte_and_version(self) -> None:
        for version in ("1.0.0-beta.10", "1.0.0-beta.11", "1.0.0-beta.12", "1.0.0-beta.13", "1.0.0-beta.14", "1.0.0-beta.15", "1.0.0-beta.16", "1.0.0-beta.17", "1.0.0-beta.18", "1.0.0-beta.19"):
            with self.subTest(version=version):
                expected = self.shared_release(version=version)
                output = self.build(output=self.website / version)
                tool = output / builder.EXPECTED_PREFIX
                for name, content in expected.items():
                    self.assertEqual((tool / name).read_bytes(), content)
                metadata = json.loads((tool / "SOURCE_RELEASE.json").read_text())
                self.assertEqual(metadata["product_version"], version)
                self.assertEqual(metadata["package_sha256"], "b" * 64)
                self.assertEqual(metadata["payload_file_count"], len(expected))

    def test_shared_release_rejects_mixed_version_urls_and_unreviewed_versions(self) -> None:
        self.shared_release()
        valid = json.loads(self.config.read_text())
        for version, url in [
            ("1.0.0-beta.9", builder.SHARED_RELEASE_URLS["1.0.0-beta.10"]),
            ("1.0.0-beta.10", builder.SHARED_RELEASE_URLS["1.0.0-beta.9"]),
            ("1.0.0-beta.11", builder.SHARED_RELEASE_URLS["1.0.0-beta.10"]),
            ("1.0.0-beta.10", builder.SHARED_RELEASE_URLS["1.0.0-beta.11"]),
            ("1.0.0-beta.12", builder.SHARED_RELEASE_URLS["1.0.0-beta.11"]),
            ("1.0.0-beta.13", builder.SHARED_RELEASE_URLS["1.0.0-beta.12"]),
            ("1.0.0-beta.14", builder.SHARED_RELEASE_URLS["1.0.0-beta.13"]),
            ("1.0.0-beta.15", builder.SHARED_RELEASE_URLS["1.0.0-beta.14"]),
            ("1.0.0-beta.16", builder.SHARED_RELEASE_URLS["1.0.0-beta.15"]),
            ("1.0.0-beta.17", builder.SHARED_RELEASE_URLS["1.0.0-beta.16"]),
            ("1.0.0-beta.18", builder.SHARED_RELEASE_URLS["1.0.0-beta.17"]),
            ("1.0.0-beta.17", builder.SHARED_RELEASE_URLS["1.0.0-beta.18"]),
            ("1.0.0-beta.18", builder.SHARED_RELEASE_URLS["1.0.0-beta.19"]),
            ("1.0.0-beta.19", builder.SHARED_RELEASE_URLS["1.0.0-beta.18"]),
            (None, builder.SHARED_RELEASE_URLS["1.0.0-beta.10"]),
        ]:
            with self.subTest(version=version, url=url):
                self.config.write_text(json.dumps(dict(valid, product_version=version, archive_url=url)))
                with self.assertRaisesRegex(builder.BuildError, "pinned reviewed release"):
                    builder.load_release_config(self.config)

    def test_beta19_config_pins_unpublished_web_payload_identity(self) -> None:
        config = json.loads((TEMPLATE / "config/figure-release.json").read_text(encoding="utf-8"))
        self.assertEqual(config["schema"], "figurePagesRelease.v2")
        self.assertEqual(config["product_version"], "1.0.0-beta.19")
        self.assertEqual(config["archive_url"], builder.SHARED_RELEASE_URLS["1.0.0-beta.19"])
        self.assertEqual(config["archive_sha256"], "04f4147a157d6ffc8dd52c87520eb3990966a59b4c459ec34c5b8c5a920e92ef")
        self.assertEqual(config["source_revision"], "16a54f3337af7e0789c74d4c66f25e406e45b0a7")
        self.assertEqual(config["package_sha256"], "93ecf1ff7612ef3c532d705eb23ebe5f058ee1703323d92e5c4284efc2f37458")
        self.assertEqual(config["payload_tree_sha256"], "45822c8e525791eaec2b452f14f9d2b371440053b9cf401ff13774c473df24a1")
        self.assertEqual(builder.load_release_config(TEMPLATE / "config/figure-release.json"), config)
        page = (TEMPLATE / "pages/superbench/index.html").read_text(encoding="utf-8")
        self.assertIn("desktop scientific workspace", page)
        self.assertIn("slide decks", page)
        self.assertIn("v1.0.0-beta.19", page)
        self.assertNotIn("presentations", page.lower())
        software = (TEMPLATE / "pages/software.html").read_text(encoding="utf-8")
        self.assertIn("slide decks", software)

    def test_beta19_archive_digest_mismatch_fails_before_build(self) -> None:
        config = json.loads((TEMPLATE / "config/figure-release.json").read_text(encoding="utf-8"))
        self.assertEqual(config["product_version"], "1.0.0-beta.19")
        self.assertEqual(config["archive_url"], builder.SHARED_RELEASE_URLS["1.0.0-beta.19"])
        self.config.write_text(json.dumps(dict(config, archive_sha256="0" * 64)), encoding="utf-8")
        with self.assertRaisesRegex(builder.BuildError, "digest mismatch"):
            self.build(output=self.website / "beta19-wrong-digest")

    def test_shared_release_rejects_tree_drift_and_files_outside_payload(self) -> None:
        self.shared_release()
        config = json.loads(self.config.read_text())
        config["payload_tree_sha256"] = "0" * 64
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(builder.BuildError, "desktop release tree"):
            self.build()
        self.shared_release([("unexpected.html", b"different runtime", None)])
        with self.assertRaisesRegex(builder.BuildError, "outside the shared payload roots"):
            self.build()

    def test_shared_release_requires_complete_pinned_identity_and_fixed_mount(self) -> None:
        self.shared_release()
        valid = json.loads(self.config.read_text())
        for field, invalid in [("source_revision", "bad"), ("package_sha256", None),
                               ("payload_tree_sha256", "c" * 63), ("destination", "other"),
                               ("archive_root", builder.EXPECTED_PREFIX),
                               ("archive_url", "https://example.com/latest.zip")]:
            with self.subTest(field=field):
                changed = dict(valid, **{field: invalid})
                self.config.write_text(json.dumps(changed))
                with self.assertRaises(builder.BuildError):
                    self.build()

    def test_approved_personal_pages_link_public_resources_and_exclude_other_private_pages(self) -> None:
        root = (TEMPLATE / "pages/index.html").read_text(encoding="utf-8")
        overview = (TEMPLATE / "pages/superbench/index.html").read_text(encoding="utf-8")
        research = (TEMPLATE / "pages/research.html").read_text(encoding="utf-8")
        software = (TEMPLATE / "pages/software.html").read_text(encoding="utf-8")
        self.assertIn('href="/research.html"', root)
        self.assertIn('href="/software.html"', root)
        self.assertIn("/superbench/", software)
        self.assertIn("/superbench/figure_tool/", overview)
        selected_figure = json.loads((TEMPLATE / "config/figure-release.json").read_text(encoding="utf-8"))
        self.assertIn("/releases/tag/v" + selected_figure["product_version"], overview)
        self.assertIn("/superbench/mirna/", overview)
        self.assertIn('id="about-title"', root)
        self.assertIn('src="assets/ian-mersich-portrait.jpg"', root)
        self.assertIn('https://scholar.google.com/citations?', root)
        self.assertIn('id="rna-to-mirna-study"', research)
        self.assertIn("Manuscript in preparation", research)
        self.assertIn('href="/research.html#rna-to-mirna-study"', software)
        self.assertIn('href="/superbench/mirna/"', software)
        self.assertIn('href="/superbench/figure_tool/"', software)
        for page in (root, research, software):
            self.assertNotIn("preview-banner", page)
            self.assertNotIn("local preview", page)
        for private_page in ("home-work.html", "home-profile.html", "superbench.html", "figure.html"):
            self.assertFalse((TEMPLATE / "pages" / private_page).exists())
            self.assertNotIn(f'href="{private_page}', root + research + software)
        for forbidden in ("manuscript", "private report", "patient", "unpublished data", "personal research"):
            self.assertNotIn(forbidden, (root + overview).casefold())
        cname = TEMPLATE / "CNAME"
        if cname.exists():
            self.assertEqual(cname.read_text(encoding="utf-8").strip(), builder.ALLOWED_CUSTOM_DOMAIN)
        self.assertTrue((TEMPLATE / "LICENSE").is_file())
        self.assertTrue((TEMPLATE / ".github/workflows/pages.yml").is_file())

    def test_custom_domain_is_validated_and_preserved_in_built_site(self) -> None:
        cname = self.website / "CNAME"
        cname.write_text(builder.ALLOWED_CUSTOM_DOMAIN + "\n", encoding="utf-8", newline="\n")
        output = self.build()
        self.assertEqual(builder._fs(output / "CNAME").read_text(encoding="utf-8"), builder.ALLOWED_CUSTOM_DOMAIN + "\n")

        cname.write_text("evil.example\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(builder.BuildError, "approved domain"):
            self.build(output=self.website / "rejected-domain")

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
