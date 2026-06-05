import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.attachments import (
    attachment_import_apply_findings,
    attachment_import_dry_run_findings,
    attachment_validation_findings,
    make_attachment_import_request,
)
from mylittleharness.cli import main
from mylittleharness.inventory import load_inventory
from tests.test_research_intake import make_live_root, make_product_root


class AttachmentImportTests(unittest.TestCase):
    def test_dry_run_reports_target_sidecar_hash_and_handoff_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_live_root(base / "root")
            source = make_source_file(base, "incoming/proposal.pdf", b"%PDF-1.7\nsample\n")
            before = snapshot_tree_bytes(root)

            findings = attachment_import_dry_run_findings(
                load_inventory(root),
                make_attachment_import_request(
                    str(source),
                    kind="vendor-proposal",
                    topic="mts-internet",
                    title="MTS internet commercial proposal",
                    received_at="2026-06-02",
                    source_label="email attachment",
                ),
            )

            self.assertEqual(before, snapshot_tree_bytes(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("attachment-import-dry-run", rendered)
            self.assertIn("project/attachments/vendor-proposals/2026-06-02-mts-internet/original.pdf", rendered)
            self.assertIn("project/attachments/vendor-proposals/2026-06-02-mts-internet/artifact.md", rendered)
            self.assertIn("sha256=", rendered)
            self.assertIn("mime_type=application/pdf", rendered)
            self.assertIn("research-import --dry-run --from-attachment", rendered)
            self.assertFalse((root / "project/attachments").exists())

    def test_apply_copies_binary_and_writes_metadata_card_as_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_live_root(base / "root")
            payload = b"%PDF-1.7\nproposal bytes\n"
            source = make_source_file(base, "incoming/proposal.pdf", payload)
            before = snapshot_tree_bytes(root)

            findings = attachment_import_apply_findings(
                load_inventory(root),
                make_attachment_import_request(
                    str(source),
                    kind="vendor-proposal",
                    topic="mts-internet",
                    title="MTS internet commercial proposal",
                    received_at="2026-06-02",
                    source_label="email attachment",
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("attachment-import-applied", rendered)
            target_dir = root / "project/attachments/vendor-proposals/2026-06-02-mts-internet"
            binary = target_dir / "original.pdf"
            card = target_dir / "artifact.md"
            self.assertEqual(payload, binary.read_bytes())
            text = card.read_text(encoding="utf-8")
            self.assertIn('type: "attachment"', text)
            self.assertIn('kind: "vendor-proposal"', text)
            self.assertIn('status: "imported"', text)
            self.assertIn('source_file: "original.pdf"', text)
            self.assertIn('mime_type: "application/pdf"', text)
            self.assertIn(f'sha256: "{hashlib.sha256(payload).hexdigest()}"', text)
            self.assertIn(f"size_bytes: {len(payload)}", text)
            self.assertIn('source: "email attachment"', text)
            self.assertIn('authority: "binary is source evidence; this md card is metadata authority"', text)
            self.assertIn("cannot approve purchase, commit, roadmap status, plans", text)

            after = snapshot_tree_bytes(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(
                [
                    "project/attachments/vendor-proposals/2026-06-02-mts-internet/artifact.md",
                    "project/attachments/vendor-proposals/2026-06-02-mts-internet/original.pdf",
                ],
                changed,
            )
            validation = attachment_validation_findings(load_inventory(root))
            rendered_validation = "\n".join(finding.render() for finding in validation)
            self.assertIn("attachment-card-ok", rendered_validation)
            self.assertFalse([finding for finding in validation if finding.severity in {"error", "warn"}])

    def test_apply_refuses_product_fixture_unsupported_extension_and_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            product_root = make_product_root(base / "product")
            source = make_source_file(base, "incoming/proposal.pdf", b"%PDF\n")
            before = snapshot_tree_bytes(product_root)

            findings = attachment_import_apply_findings(
                load_inventory(product_root),
                make_attachment_import_request(str(source), kind="vendor-proposal", topic="mts-internet", title="MTS proposal"),
            )

            self.assertEqual(before, snapshot_tree_bytes(product_root))
            self.assertIn("product-source compatibility fixture", "\n".join(finding.render() for finding in findings))

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_live_root(base / "root")
            source = make_source_file(base, "incoming/proposal.txt", b"not supported\n")
            before = snapshot_tree_bytes(root)

            findings = attachment_import_apply_findings(
                load_inventory(root),
                make_attachment_import_request(str(source), kind="vendor-proposal", topic="mts-internet", title="MTS proposal"),
            )

            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertIn("supported extensions", "\n".join(finding.render() for finding in findings))

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_live_root(base / "root")
            source = make_source_file(base, "incoming/proposal.pdf", b"%PDF\n")
            existing = root / f"project/attachments/vendor-proposals/{date.today().isoformat()}-mts-internet/artifact.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n", encoding="utf-8")
            before = snapshot_tree_bytes(root)

            findings = attachment_import_apply_findings(
                load_inventory(root),
                make_attachment_import_request(str(source), kind="vendor-proposal", topic="mts-internet", title="MTS proposal"),
            )

            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertIn("target metadata card already exists", "\n".join(finding.render() for finding in findings))

    def test_cli_dry_run_and_apply_use_attachment_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_live_root(base / "root")
            source = make_source_file(base, "incoming/proposal.pdf", b"%PDF\ncli\n")

            dry_stdout = io.StringIO()
            with contextlib.redirect_stdout(dry_stdout):
                dry_code = main(
                    [
                        "--root",
                        str(root),
                        "attachment-import",
                        "--dry-run",
                        "--file",
                        str(source),
                        "--kind",
                        "vendor-proposal",
                        "--topic",
                        "mts-internet",
                        "--title",
                        "MTS internet commercial proposal",
                    ]
                )
            self.assertEqual(0, dry_code)
            self.assertIn("attachment-import --dry-run", dry_stdout.getvalue())
            self.assertFalse((root / "project/attachments").exists())

            apply_stdout = io.StringIO()
            with contextlib.redirect_stdout(apply_stdout):
                apply_code = main(
                    [
                        "--root",
                        str(root),
                        "attachment-import",
                        "--apply",
                        "--file",
                        str(source),
                        "--kind",
                        "vendor-proposal",
                        "--topic",
                        "mts-internet",
                        "--title",
                        "MTS internet commercial proposal",
                    ]
                )
            self.assertEqual(0, apply_code)
            self.assertIn("attachment-import-applied", apply_stdout.getvalue())
            self.assertTrue((root / f"project/attachments/vendor-proposals/{date.today().isoformat()}-mts-internet/artifact.md").is_file())


def make_source_file(base: Path, rel_path: str, payload: bytes) -> Path:
    path = base / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def snapshot_tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
