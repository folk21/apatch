"""Producer port and compatibility regression checks for handoff modularization."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch
import unittest
import zipfile

import apatch_pack
import apatch_preflight
from apatch_lib import artifact_packaging as legacy_packaging
from apatch_lib import artifact_preflight as legacy_preflight
from apatch_lib.core.api import Abort
from apatch_lib.handoff.api import (PackagingResult, PreflightResult,
                                   ProducerOperations, SourceCandidates,
                                   VerifiedSourceProducer)
from apatch_lib.handoff.producer import models, packaging, preflight
from tests._support import LocalGitFixture


class HandoffProducerPortTests(LocalGitFixture):
    def setUp(self):
        super().setUp()
        (self.root / "new.txt").write_text("new\n")
        self.producer: ProducerOperations = VerifiedSourceProducer()

    def test_production_port_is_structural_and_has_no_git_or_zip_side_effects_on_discovery(self):
        self.assertIsInstance(self.producer, ProducerOperations)
        candidates = self.producer.discover(self.root)
        self.assertEqual(candidates.include, ("new.txt",))
        self.assertEqual(candidates.untracked, ("new.txt",))
        self.assertEqual(candidates.head, self.head)
        self.assertIsInstance(candidates, SourceCandidates)
        self.assertFalse((self.base / "downloads" / "result.zip").exists())

    def test_preflight_and_pack_share_producer_identity_and_admission(self):
        evidence = self.producer.preflight(self.root, self.bin)
        self.assertIsInstance(evidence, PreflightResult)
        self.assertEqual(evidence.head, self.head)
        path = self.base / "downloads" / "example_service-PATCH-producer.zip"
        result = self.producer.pack(
            self.root, self.bin, path, branch="feature/producer-port",
            message="refactor: producer port\n\nVerify source bytes.",
            included=("new.txt",))
        self.assertIsInstance(result, PackagingResult)
        self.assertEqual(result.source.head, self.head)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read("example_service/new.txt"), b"new\n")
            self.assertIsNone(archive.testzip())
        original = path.read_bytes()
        with self.assertRaisesRegex(Abort, "already exists"):
            self.producer.pack(
                self.root, self.bin, path, branch="feature/producer-port",
                message="refactor: producer port", included=("new.txt",))
        self.assertEqual(path.read_bytes(), original)

    def test_legacy_value_classes_and_preflight_are_identity_aliases(self):
        self.assertIs(legacy_packaging.PackagingResult, models.PackagingResult)
        self.assertIs(legacy_packaging.SourceCandidates, models.SourceCandidates)
        self.assertIs(legacy_preflight.PreflightResult, models.PreflightResult)
        self.assertIs(legacy_preflight.preflight, preflight.preflight)
        self.assertIs(legacy_packaging.discover_source_paths, packaging.discover_source_paths)

    def test_legacy_packaging_mock_seam_preserves_failing_preflight(self):
        destination = self.base / "downloads" / "result.zip"
        with patch.object(legacy_packaging, "preflight", side_effect=Abort("injected")):
            with self.assertRaisesRegex(Abort, "injected"):
                legacy_packaging.pack_source(
                    self.root, self.bin, destination, branch="feature/producer-port",
                    message="refactor: producer port", included=("new.txt",))
        self.assertFalse(destination.exists())


class FakeProducer:
    def __init__(self):
        self.calls = []

    def discover(self, project: Path) -> SourceCandidates:
        self.calls.append(("discover", project))
        return SourceCandidates("service", "main", "a" * 40, ("new.txt",), (), ("new.txt",))

    def preflight(self, project: Path, installation: Path, *,
                  prepare: bool = False) -> PreflightResult:
        self.calls.append(("preflight", project, prepare))
        return PreflightResult("service", "main", "a" * 40, ("new.txt",),
                               "b" * 64, prepare, int(prepare), 1)

    def pack(self, project: Path, installation: Path, destination: Path, *,
             branch: str, message: str, included: tuple[str, ...],
             deleted: tuple[str, ...] = (), prepare: bool = False,
             base_commit: str | None = None) -> PackagingResult:
        self.calls.append(("pack", project, destination, included, deleted))
        evidence = self.preflight(project, installation, prepare=prepare)
        return PackagingResult(str(destination), "c" * 64, 200, evidence,
                               included, deleted)


class ProducerCliCompositionTests(unittest.TestCase):
    def test_fake_port_drives_discovery_json_without_git_or_filesystem(self):
        source = FakeProducer()
        self.assertIsInstance(source, ProducerOperations)
        output = StringIO()
        with redirect_stdout(output):
            code = apatch_pack.main(["--project", "/tmp/source", "--discover", "--json"],
                                    producer=source)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["include"], ["new.txt"])
        self.assertEqual(source.calls[0], ("discover", Path("/tmp/source")))

    def test_fake_port_drives_preflight_and_pack_json_without_side_effects(self):
        source = FakeProducer()
        output = StringIO()
        with redirect_stdout(output):
            code = apatch_preflight.main(["--project", "/tmp/source", "--json"],
                                         producer=source)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")
        self.assertEqual(source.calls[0][0], "preflight")

        output = StringIO()
        with redirect_stdout(output):
            code = apatch_pack.main([
                "--project", "/tmp/source", "--output", "/tmp/result.zip",
                "--branch", "feature/producer-port", "--message", "test: packaging",
                "--include", "new.txt", "--json"], producer=source)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["files"], ["new.txt"])
        self.assertEqual(source.calls[-2][0], "pack")

    def test_fake_port_failure_returns_machine_readable_failure_without_zip(self):
        class FailingProducer(FakeProducer):
            def pack(self, *args, **kwargs):
                raise Abort("source was modified")

        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = apatch_pack.main([
                "--output", "/tmp/will-not-be-written.zip", "--branch", "feature/failure",
                "--message", "test: failure", "--include", "new.txt", "--json"],
                producer=FailingProducer())
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out.getvalue())["status"], "failed")
        self.assertIn("source was modified", err.getvalue())


if __name__ == "__main__":
    unittest.main()
