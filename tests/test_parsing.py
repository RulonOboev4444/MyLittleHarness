from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.parsing import extract_headings, extract_path_refs, parse_frontmatter


class ParsingTests(unittest.TestCase):
    def test_tolerant_frontmatter_parses_scalars_and_lists(self) -> None:
        parsed = parse_frontmatter(
            '---\nstatus: "active"\nreferences:\n  - "README.md"\n  - "project/project-state.md"\n---\n# Body\n'
        )
        self.assertTrue(parsed.has_frontmatter)
        self.assertEqual(parsed.data["status"], "active")
        self.assertEqual(parsed.data["references"], ["README.md", "project/project-state.md"])
        self.assertEqual(parsed.errors, [])

    def test_malformed_frontmatter_reports_error(self) -> None:
        parsed = parse_frontmatter("---\nstatus active\n# Body\n")
        self.assertTrue(parsed.has_frontmatter)
        self.assertIn("no closing marker", parsed.errors[0])

    def test_heading_and_path_extraction(self) -> None:
        text = '# Title\nSee `project/project-state.md`, ".agents/docmap.yaml", and [README](README.md).\n'
        headings = extract_headings(text)
        refs = extract_path_refs(text)
        self.assertEqual(headings[0].title, "Title")
        targets = {ref.target for ref in refs}
        self.assertIn("project/project-state.md", targets)
        self.assertIn(".agents/docmap.yaml", targets)
        self.assertIn("README.md", targets)


if __name__ == "__main__":
    unittest.main()

