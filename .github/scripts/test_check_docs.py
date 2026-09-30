"""Success and failure cases for the offline documentation boundary."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_docs as docs


class DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = docs.git(docs.ROOT, "show", f"{docs.BASELINE_COMMIT}:docs/PRD.md")
        cls.prd = docs.safe_path(docs.ROOT, "docs/PRD.md").read_bytes()
        cls.readme = docs.safe_path(docs.ROOT, "README.md").read_bytes()

    def setUp(self):
        # All temporary files, including simulated external targets, stay in clone.
        self.temp = tempfile.TemporaryDirectory(prefix="docs-test-", dir=docs.ROOT)
        self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name)
        self.root = self.fixture / "repo"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs/PRD.md").write_bytes(self.prd)
        (self.root / "README.md").write_bytes(self.readme)

    def check_fixture(self, tracked=b"README.md\x00docs/PRD.md\x00"):
        with patch.object(docs, "git", side_effect=[self.baseline, tracked]):
            return docs.check_repository(self.root)

    def test_actual_repository(self):
        count, missing = docs.check_repository(docs.ROOT)
        self.assertGreaterEqual(count, 2)
        self.assertEqual(missing, docs.HISTORICAL_LINKS)

    def test_original_bytes_cannot_change(self):
        changed = self.prd.replace(b"Status: Active", b"Status: Draft", 1)
        with self.assertRaisesRegex(docs.DocsError, "original bytes"):
            docs.check_prd(changed, self.baseline)

    def test_missing_boundary_or_historical_entry(self):
        for removed in (docs.BOUNDARY, b"- `AGENTS.md`\n"):
            with self.subTest(removed=removed[:40]), self.assertRaises(docs.DocsError):
                docs.check_prd(self.prd.replace(removed, b"", 1), self.baseline)

    def test_unexpected_baseline(self):
        with self.assertRaisesRegex(docs.DocsError, "baseline"):
            docs.check_prd(self.prd, self.baseline + b"\n")

    def test_missing_or_broken_readme_link(self):
        for content in (self.readme.replace(b"[Pige Product Requirements](docs/PRD.md)", b"Pige Product Requirements"),
                        self.readme + b"\n[missing](docs/absent.md)\n"):
            with self.subTest(content=content[-45:]):
                (self.root / "README.md").write_bytes(content)
                with self.assertRaises(docs.DocsError):
                    self.check_fixture()

    def test_release_and_outdated_status_claims(self):
        for claim in (b"Alpha is released.", b"Production-ready.", b"No tests or GitHub Actions workflows exist."):
            with self.subTest(claim=claim), self.assertRaises(docs.DocsError):
                data = self.readme + b"\n" + claim
                docs.check_readme(data, docs.markdown_body(data, "README.md"))

    def test_encoding_and_fences(self):
        for data in (b"\xff", b"\x00", b"```text\nunclosed\n", b"~~~~\n~~~\n", b"```bad`info\n```\n"):
            with self.subTest(data=data), self.assertRaises(docs.DocsError):
                docs.markdown_body(data, "bad.md")
        body = docs.markdown_body(b"```text\n[ignored](missing.md)\n````\n`[ignored](missing.md)`", "good.md")
        self.assertEqual(list(docs.link_targets(body, "good.md")), [])

    def test_links_images_references_and_network(self):
        (self.root / "docs/a(b).md").write_text("# Local\n", encoding="utf-8")
        body = "[inline](docs/a(b).md#local) ![image](docs/a%28b%29.md) [ref][r] [r]\n[r]: <docs/a(b).md>\n[web](https://example.invalid/no-request)"
        self.assertEqual(docs.check_links(self.root, "README.md", body), set())
        for broken in ("![image](missing.png)", "[ref][missing]", "[bad](unterminated"):
            with self.subTest(broken=broken), self.assertRaises(docs.DocsError):
                docs.check_links(self.root, "README.md", broken)

    def test_historical_exception_only_applies_to_prd(self):
        with self.assertRaisesRegex(docs.DocsError, "broken local link"):
            docs.check_links(self.root, "README.md", "[owner](docs/START_HERE_FOR_AI_AGENTS.md)")

    def test_traversal_and_protected_paths_not_read(self):
        for target in ("../outside.md", "%2e%2e/outside.md", "/outside.md", ".env", ".aws/config"):
            with self.subTest(target=target), patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")):
                with self.assertRaises(docs.DocsError):
                    docs.check_links(self.root, "README.md", f"[unsafe]({target})")

    def test_external_symlinks_not_read(self):
        outside = self.fixture / "outside.md"
        outside.write_text("External sentinel", encoding="utf-8")
        (self.root / "linked.md").symlink_to(outside)
        (self.root / "linked-dir").symlink_to(self.fixture, target_is_directory=True)
        for target in ("linked.md", "linked-dir/outside.md"):
            with self.subTest(target=target), patch.object(Path, "read_bytes", side_effect=AssertionError("external read")):
                with self.assertRaisesRegex(docs.DocsError, "symlink"):
                    docs.check_links(self.root, "README.md", f"[unsafe]({target})")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("external source read")):
            with self.assertRaisesRegex(docs.DocsError, "symlink"):
                docs.safe_path(self.root, "linked.md")

    def test_tracked_markdown_only(self):
        (self.root / "untracked.md").write_bytes(b"\xff")
        self.assertEqual(self.check_fixture()[0], 2)
        with self.assertRaisesRegex(docs.DocsError, "UTF-8"):
            self.check_fixture(b"untracked.md\x00")


if __name__ == "__main__":
    unittest.main()
