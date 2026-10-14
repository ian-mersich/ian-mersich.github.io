"""Verify isolated, pinned miRNA distribution without changing Figure assets."""
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from tests.test_figure_pages_consumer import builder, zip_bytes


class MiRNAPagesConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.website = self.root / "website"
        self.pages = self.website / "pages"
        self.pages.mkdir(parents=True)
        (self.pages / "index.html").write_text("<h1>Ian Mersich</h1>", encoding="utf-8")
        self.license = self.website / "LICENSE"
        self.license.write_text("Apache-2.0", encoding="utf-8")
        self.figure = self.root / "figure.zip"
        self.figure.write_bytes(zip_bytes())
        self.figure_config = self.root / "figure.json"
        self.figure_config.write_text(json.dumps({
            "schema": "figurePagesRelease.v1", "product_version": "1.0.0-beta.6",
            "archive_url": builder.EXPECTED_URL, "archive_root": builder.EXPECTED_PREFIX,
            "archive_sha256": hashlib.sha256(self.figure.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        self.mirna = self.root / "mirna.zip"
        self.entries = [(name, b"frozen artifact", None) for name in builder.MIRNA_REQUIRED_FILES]
        self.manifest = {
            "publication_status": "cleared", "release_version": "1.0.0-beta.1",
            "model": {"id": "s09_p1_browser_v1"},
        }
        self.metadata = {
            "publication_status": "cleared", "release_version": "1.0.0-beta.1",
            "model_id": "s09_p1_browser_v1",
        }
        self.entries = [(name, json.dumps(self.manifest if name == "release_manifest.json" else self.metadata).encode() if name in ("release_manifest.json", "RELEASE_METADATA.json") else content, mode) for name, content, mode in self.entries]
        self.mirna.write_bytes(zip_bytes(self.entries))
        self.mirna_config = self.root / "mirna.json"
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **changes):
        data = {
            "schema": "mirnaPagesRelease.v1", "product_version": "1.0.0-beta.1",
            "publication_status": "cleared", "model_id": "s09_p1_browser_v1",
            "destination": "superbench/mirna", "archive_root": "",
            "archive_url": "https://github.com/ian-mersich/mirna-predictor/releases/download/v1.0.0-beta.1/mirna-web.zip",
            "archive_sha256": hashlib.sha256(self.mirna.read_bytes()).hexdigest(),
        }
        data.update(changes)
        self.mirna_config.write_text(json.dumps(data), encoding="utf-8")

    def build(self):
        return builder.build_site(
            config_path=self.figure_config, archive_path=self.figure,
            pages_dir=self.pages, website_dir=self.website, license_path=self.license,
            mirna_config_path=self.mirna_config, mirna_archive_path=self.mirna,
        )

    def test_nested_tool_preserves_exact_assets_and_figure(self):
        output = self.build()
        self.assertEqual((output / "superbench/mirna/data/model/weights.bin").read_bytes(), b"frozen artifact")
        self.assertEqual((output / "superbench/figure_tool/app/main.js").read_bytes(), b"console.log('ready')")
        self.assertEqual((output / "index.html").read_text(), "<h1>Ian Mersich</h1>")
        record = json.loads((output / "MIRNA_RELEASE.json").read_text())
        self.assertEqual(record["archive_sha256"], hashlib.sha256(self.mirna.read_bytes()).hexdigest())
        self.assertEqual(record["model_id"], "s09_p1_browser_v1")

    def test_uncleared_or_changed_identity_rejected_before_output(self):
        for change in (
            {"publication_status": "pending"}, {"model_id": "unqualified-model"},
            {"destination": "superbench/figure_tool"}, {"archive_root": "some-root"},
        ):
            with self.subTest(change=change):
                self.write_config(**change)
                with self.assertRaises(builder.BuildError):
                    self.build()
                self.assertFalse((self.website / "_site").exists())

    def test_floating_or_untrusted_archive_url_rejected(self):
        for url in (
            "https://github.com/ian-mersich/mirna-predictor/releases/latest/mirna-web.zip",
            "http://github.com/ian-mersich/mirna-predictor/releases/download/v1/mirna-web.zip",
            "https://other.example/mirna.zip",
        ):
            self.write_config(archive_url=url)
            with self.assertRaises(builder.BuildError):
                self.build()

    def test_wrong_digest_leaves_no_partial_output(self):
        self.write_config(archive_sha256="f" * 64)
        with self.assertRaises(builder.BuildError):
            self.build()
        self.assertFalse((self.website / "_site").exists())
        self.assertEqual(list(self.website.glob(".figure-pages-build-*")), [])

    def test_artifact_clearance_and_version_must_match_config(self):
        for change in ({"publication_status": "pending"}, {"release_version": "another-version"}):
            with self.subTest(change=change):
                manifest = {**self.manifest, **change}
                entries = [(name, json.dumps(manifest).encode() if name == "release_manifest.json" else content, mode) for name, content, mode in self.entries]
                self.mirna.write_bytes(zip_bytes(entries))
                self.write_config()
                with self.assertRaises(builder.BuildError):
                    self.build()
                self.assertFalse((self.website / "_site").exists())

    def test_license_scope_files_required(self):
        self.mirna.write_bytes(zip_bytes([row for row in self.entries if row[0] != "MODEL_AND_RESULTS_LICENSE.md"]))
        self.write_config()
        with self.assertRaises(builder.BuildError):
            self.build()

    def test_traversal_duplicates_symlinks_and_missing_assets_rejected(self):
        cases = (
            self.entries + [("../../index.html", b"overwrite", None)],
            self.entries + [("index.html", b"duplicate", None)],
            self.entries + [("outside", b"../outside", stat.S_IFLNK | 0o777)],
            [entry for entry in self.entries if entry[0] != "data/model/weights.bin"],
        )
        for entries in cases:
            with self.subTest(entries=entries):
                self.mirna.write_bytes(zip_bytes(entries))
                self.write_config()
                with self.assertRaises(builder.BuildError):
                    self.build()
                self.assertFalse((self.website / "_site").exists())


if __name__ == "__main__":
    unittest.main()
