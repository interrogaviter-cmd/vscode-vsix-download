"""Offline regression checks for the catalog and verified VSIX downloader.

Run from the repository root: python -m unittest discover -s tests -v
No test contacts the Marketplace or downloads a real extension.
"""
import ast
import contextlib
import hashlib
import io
import json
import re
import struct
import shutil
import tokenize
import unittest
import uuid
from pathlib import Path
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

import requests

import download_vscode_extensions as downloader
import extension_catalog as catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
ID_PATTERN = re.compile(r"[a-z0-9_-]+\.[a-z0-9_-]+", re.IGNORECASE)
QUOTED_ID_PATTERN = re.compile(r"['\"]([a-z0-9_-]+\.[a-z0-9_-]+)['\"]", re.IGNORECASE)


@contextlib.contextmanager
def temporary_directory():
    # Keep fixtures inside the writable workspace on restricted Windows hosts.
    # Python 3.14 tempfile's mode=0700 ACL excludes some Windows sandbox tokens.
    temporary = TEST_ROOT / ("fixture-" + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        yield str(temporary)
    finally:
        assert temporary.resolve().parent == TEST_ROOT
        shutil.rmtree(temporary)


def legacy_extension_ids(path):
    """Read every literal/comment ID, including lists later overwritten.

    Parse text instead of importing old scripts, whose imports configure logs.
    Ignore docstrings: the historical CLI documents the placeholder
    ``publisher.name``, which is not a real extension.
    """
    source = path.read_text(encoding="utf-8")
    docstring_ranges = []
    extension_list_ranges = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is not None:
                first = node.body[0]
                docstring_ranges.append((first.lineno, first.end_lineno))
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in ("EXTENSIONS", "EXTENSIONS_LIST")
                for target in node.targets):
            extension_list_ranges.append((node.lineno, node.end_lineno))
    found = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if any(start <= token.start[0] <= end for start, end in docstring_ranges):
            continue
        if token.type == tokenize.COMMENT:
            found.update(match.lower() for match in QUOTED_ID_PATTERN.findall(token.string))
        elif token.type == tokenize.STRING and any(
                start <= token.start[0] <= end for start, end in extension_list_ranges):
            try:
                value = ast.literal_eval(token.string)
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, str) and ID_PATTERN.fullmatch(value):
                found.add(value.lower())
    return found


def make_vsix(extension_id="example.plugin", version="1.0.0", platform="linux-x64",
              manifest_id=None, binaries=None):
    """Create a minimal ZIP with independently constructed VSIX metadata."""
    publisher, name = extension_id.split(".", 1)
    package = {"publisher": publisher, "name": name, "version": version,
               "engines": {"vscode": "^1.95.0"},
               "extensionDependencies": ["example.dependency"],
               "extensionPack": ["example.pack-member"]}
    root = ET.Element("PackageManifest", xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011")
    metadata = ET.SubElement(root, "Metadata")
    attributes = {"Id": manifest_id or name, "Publisher": publisher, "Version": version}
    if platform is not None:
        attributes["TargetPlatform"] = platform
    ET.SubElement(metadata, "Identity", attributes)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("extension/package.json", json.dumps(package))
        archive.writestr("extension.vsixmanifest", ET.tostring(root))
        for filename, content in (binaries or {}).items():
            archive.writestr(filename, content)
    return result.getvalue()


def elf_header(machine=62):
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, machine)
    return bytes(header)


def pe_header(machine=0x8664):
    header = bytearray(70)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 64)
    header[64:68] = b"PE\0\0"
    struct.pack_into("<H", header, 68, machine)
    return bytes(header)


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        # An accidental unmocked request fails immediately, even without a network.
        guard = mock.patch("requests.sessions.Session.request",
                           side_effect=AssertionError("Tests must never use the network"))
        guard.start()
        self.addCleanup(guard.stop)


class CatalogTests(OfflineTestCase):
    def test_history_covers_all_four_legacy_scripts_including_comments(self):
        paths = sorted((REPO_ROOT / "legacy").glob("download*.py"))
        self.assertEqual(len(paths), 4)
        historical_ids = set().union(*(legacy_extension_ids(path) for path in paths))
        self.assertEqual(len(historical_ids), 69)
        self.assertNotIn("publisher.name", historical_ids)
        self.assertEqual(historical_ids, set(catalog.HISTORICAL_EXTENSIONS))
        self.assertEqual(len(catalog.HISTORICAL_EXTENSIONS), len(historical_ids))
        self.assertTrue(historical_ids.issubset(catalog.EXTENSIONS_CANDIDATES))
        self.assertEqual(len(catalog.EXTENSIONS_CANDIDATES),
                         len(set(catalog.EXTENSIONS_CANDIDATES)))

    def test_aliases_are_case_insensitive_and_deduplicated_in_input_order(self):
        self.assertEqual(catalog.resolve_extensions([
            " CODEX ", "OpenAI.ChatGPT", "Claude_Code", "CLAUDE CODE",
            "CLI", "cline", "Saoudrizwan.Claude-Dev", "MS-Python.Python",
        ]), ["openai.chatgpt", "anthropic.claude-code", "saoudrizwan.claude-dev",
             "ms-python.python"])

    def test_cloud_code_and_claude_code_have_distinct_aliases(self):
        self.assertEqual(catalog.resolve_extensions(["Cloud Code", "Claude Code", "CLI"]),
                         ["googlecloudtools.cloudcode", "anthropic.claude-code",
                          "saoudrizwan.claude-dev"])
        self.assertEqual(catalog.resolve_extensions(["cloudcode", "google-cloud-code"]),
                         ["googlecloudtools.cloudcode"])

    def test_invalid_aliases_and_paths_are_rejected(self):
        for token in ("unknown-alias", "../example.plugin", "example/plugin", "", "a.b.c"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                catalog.resolve_extensions([token])


class CommandLineTests(OfflineTestCase):
    def run_without_download(self, arguments):
        with temporary_directory() as temporary:
            output_path = Path(temporary) / "must-not-exist"
            stdout = io.StringIO()
            with mock.patch.object(downloader, "ExtensionDownloader",
                                   side_effect=AssertionError("No downloader should be created")), \
                    mock.patch.object(downloader.requests, "Session",
                                      side_effect=AssertionError("No session should be created")), \
                    contextlib.redirect_stdout(stdout):
                result = downloader.main(arguments + ["--output", str(output_path)])
            self.assertEqual(result, 0)
            self.assertFalse(output_path.exists())
            return stdout.getvalue()

    def test_dry_run_resolves_aliases_without_network_or_output_files(self):
        output = self.run_without_download([
            "--dry-run", "--extensions", "Cloud Code", "CLI", "Cline", "codex",
            "--platforms", "linux-x64", "linux-x64",
        ])
        config = json.loads(output)
        self.assertEqual(config["extensions"], ["googlecloudtools.cloudcode",
                         "saoudrizwan.claude-dev", "openai.chatgpt"])
        self.assertEqual(config["platforms"], ["linux-x64"])

    def test_listing_shows_every_candidate_and_alias_without_side_effects(self):
        output = self.run_without_download(["--list-extensions"])
        for extension_id in catalog.EXTENSIONS_CANDIDATES:
            self.assertIn(extension_id, output)
        for alias in ("cloud-code", "claude-code", "cline", "cli"):
            self.assertIn(alias, output)

    def test_all_dry_run_selects_the_complete_catalog(self):
        config = json.loads(self.run_without_download(["--all", "--dry-run"]))
        self.assertEqual(config["extensions"], catalog.EXTENSIONS_CANDIDATES)

    def test_pinned_version_accepts_aliases_for_the_same_extension(self):
        config = json.loads(self.run_without_download([
            "--dry-run", "--extensions", "CLI", "Cline", "--version", "1.0.0",
        ]))
        self.assertEqual(config["extensions"], ["saoudrizwan.claude-dev"])
        self.assertEqual(config["version"], "1.0.0")


class VersionSelectionTests(OfflineTestCase):
    def test_numeric_order_and_platform_filter_ignore_api_order(self):
        builds = [{"version": "1.9.0", "targetPlatform": "linux-x64"},
                  {"version": "99.0.0", "targetPlatform": "linux-arm64"},
                  {"version": "98.0.0", "targetPlatform": "win32-x64"},
                  {"version": "1.10.0", "targetPlatform": "linux-x64"}]
        self.assertIs(downloader.select_build(builds, "linux-x64"), builds[3])

    def test_stability_checks_both_marketplace_property_and_version(self):
        builds = [{"version": "2.0.0", "targetPlatform": "linux-x64"},
                  {"version": "4.0.0", "properties": [
                      {"key": downloader.PRE_RELEASE, "value": "TRUE"}]},
                  {"version": "5.0.0rc1", "targetPlatform": "linux-x64"}]
        self.assertIs(downloader.select_build(builds, "linux-x64"), builds[0])
        self.assertIs(downloader.select_build(builds, "linux-x64", allow_preview=True), builds[2])

    def test_same_version_prefers_platform_specific_build(self):
        builds = [{"version": "1.10.0"},
                  {"version": "1.10.0", "targetPlatform": "linux-x64"},
                  {"version": "1.9.0", "targetPlatform": "linux-x64"}]
        self.assertIs(downloader.select_build(builds, "linux-x64"), builds[1])
        # A newer universal version wins over an older platform-specific version.
        builds.append({"version": "1.11.0", "targetPlatform": "universal"})
        self.assertIs(downloader.select_build(builds, "linux-x64"), builds[3])

    def test_missing_target_uses_universal_and_never_other_architecture(self):
        for platform in (None, "", "universal"):
            with self.subTest(platform=platform):
                universal = {"version": "1.0.0", "targetPlatform": platform}
                self.assertIs(downloader.select_build([
                    {"version": "9.0.0", "targetPlatform": "win32-x64"}, universal],
                    "linux-x64"), universal)
        with self.assertRaises(ValueError):
            downloader.select_build([{"version": "9.0.0", "targetPlatform": "linux-arm64"}],
                                    "linux-x64")

    def test_pin_and_invalid_versions(self):
        builds = [{"version": "invalid", "targetPlatform": "linux-x64"},
                  {"version": "1.0.0"}, {"version": "2.0.0"}]
        self.assertIs(downloader.select_build(builds, "linux-x64", pinned="1.0.0"), builds[1])
        with self.assertRaises(ValueError):
            downloader.select_build(builds, "linux-x64", pinned="3.0.0")


class MainWorkflowTests(OfflineTestCase):
    def invoke_main(self, output, session, extra_arguments=()):
        logger = downloader.logging.getLogger()
        previous_handlers = list(logger.handlers)
        previous_level = logger.level
        created_handlers = []
        original_factory = downloader.logging.FileHandler

        def capture_handler(*arguments, **keywords):
            handler = original_factory(*arguments, **keywords)
            created_handlers.append(handler)
            return handler

        with mock.patch.object(downloader.requests, "Session", return_value=session), \
                mock.patch.object(downloader.logging, "FileHandler", side_effect=capture_handler), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                result = downloader.main(["--extensions", "example.plugin", "--output", output,
                                          "--attempts", "1"] + list(extra_arguments))
            finally:
                session.close.assert_called_once()
                self.assertEqual(logger.handlers, previous_handlers)
                self.assertEqual(logger.level, previous_level)
                self.assertEqual(len(created_handlers), 1)
                self.assertIsNone(created_handlers[0].stream)
        return result

    def marketplace_session(self, versions):
        session = mock.MagicMock()
        session.post.return_value.__enter__.return_value.json.return_value = {
            "results": [{"extensions": [{"publisher": {"publisherName": "example"},
                                        "extensionName": "plugin", "versions": versions}]}]}
        return session

    def test_success_manifest_records_both_targets_and_reuses_universal_package(self):
        content = make_vsix(platform=None)
        session = self.marketplace_session([{"version": "1.0.0"}])
        session.get.return_value.__enter__.return_value.iter_content.return_value = [content]
        with temporary_directory() as temporary:
            self.assertEqual(self.invoke_main(temporary, session), 0)
            records = json.loads((Path(temporary) / "download_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([record["target"] for record in records], ["win32-x64", "linux-x64"])
            self.assertEqual([record["status"] for record in records], ["downloaded", "existing"])
            self.assertEqual(records[0]["path"], records[1]["path"])
            self.assertEqual(records[0]["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(records[0]["dependencies"], ["example.dependency"])
            self.assertFalse(list(Path(temporary).rglob("*.part")))
            self.assertEqual(len(list(Path(temporary).rglob("*.vsix"))), 1)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(session.get.call_args.kwargs["params"], {})

    def test_query_failure_writes_failure_manifest_and_returns_nonzero(self):
        session = mock.MagicMock()
        session.post.return_value.__enter__.return_value.json.return_value = {"results": []}
        with temporary_directory() as temporary:
            self.assertEqual(self.invoke_main(temporary, session), 1)
            records = json.loads((Path(temporary) / "download_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["extension"], "example.plugin")
            self.assertEqual(records[0]["status"], "failed")
            self.assertTrue(records[0]["error"])
            self.assertFalse(list(Path(temporary).rglob("*.part")))
        session.get.assert_not_called()

    def test_download_failure_writes_target_failure_and_removes_partial_file(self):
        def interrupted(_chunk_size):
            yield b"incomplete package"
            raise requests.ConnectionError("simulated failed stream")

        session = self.marketplace_session([{"version": "1.0.0", "targetPlatform": "linux-x64"}])
        session.get.return_value.__enter__.return_value.iter_content.side_effect = interrupted
        with temporary_directory() as temporary:
            self.assertEqual(self.invoke_main(temporary, session, ["--platforms", "linux-x64"]), 1)
            records = json.loads((Path(temporary) / "download_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["target"], "linux-x64")
            self.assertEqual(records[0]["status"], "failed")
            self.assertIn("simulated failed stream", records[0]["error"])
            self.assertFalse(list(Path(temporary).rglob("*.part")))
            self.assertFalse(list(Path(temporary).rglob("*.vsix")))

    def test_keyboard_interrupt_still_closes_network_and_log_resources(self):
        session = mock.MagicMock()
        session.post.side_effect = KeyboardInterrupt()
        with temporary_directory() as temporary, self.assertRaises(KeyboardInterrupt):
            self.invoke_main(temporary, session)


class VsixValidationTests(OfflineTestCase):
    def validate_bytes(self, contents, extension_id="example.plugin", version="1.0.0",
                       actual="linux-x64", target="linux-x64"):
        with temporary_directory() as temporary:
            path = Path(temporary) / "test.vsix"
            path.write_bytes(contents)
            return downloader.validate_vsix(path, extension_id, version, actual, target)

    def test_valid_manifest_preserves_engine_dependencies_and_pack(self):
        metadata = self.validate_bytes(make_vsix(manifest_id="Example.Plugin"))
        self.assertEqual(metadata, {"declared_platform": "linux-x64",
                         "vscode_engine": "^1.95.0",
                         "dependencies": ["example.dependency"],
                         "extension_pack": ["example.pack-member"]})

    def test_universal_package_without_target_platform_is_accepted(self):
        metadata = self.validate_bytes(make_vsix(platform=None), actual="universal")
        self.assertEqual(metadata["declared_platform"], "universal")

    def test_package_id_and_version_mismatches_are_rejected(self):
        for package in (make_vsix(extension_id="different.plugin"),
                        make_vsix(manifest_id="different"), make_vsix(version="2.0.0")):
            with self.subTest(package=package[:16]), self.assertRaises(ValueError):
                self.validate_bytes(package)

    def test_wrong_platform_or_claimed_universal_package_is_rejected(self):
        for actual, target in (("linux-x64", "linux-x64"),
                               ("universal", "linux-x64"),
                               ("win32-x64", "linux-x64")):
            with self.subTest(actual=actual, target=target), self.assertRaises(ValueError):
                self.validate_bytes(make_vsix(platform="win32-x64"), actual=actual, target=target)

    def test_corrupt_zip_and_crc_damage_are_rejected(self):
        with self.assertRaises(zipfile.BadZipFile):
            self.validate_bytes(b"not a VSIX zip archive")
        original = make_vsix()
        damaged = bytearray(original)
        position = original.index(b"example.dependency")
        damaged[position] ^= 1
        with self.assertRaises(ValueError):
            self.validate_bytes(bytes(damaged))

    def test_codex_checks_real_linux_binary_architecture(self):
        filename = "extension/bin/linux-x86_64/codex"
        self.validate_bytes(make_vsix(extension_id="openai.chatgpt",
                                     binaries={filename: elf_header()}), extension_id="openai.chatgpt")
        for binary in (b"not ELF", elf_header(machine=183)):
            with self.subTest(binary=binary[:20]), self.assertRaises(ValueError):
                self.validate_bytes(make_vsix(extension_id="openai.chatgpt",
                                             binaries={filename: binary}), extension_id="openai.chatgpt")
        with self.assertRaises(ValueError):
            self.validate_bytes(make_vsix(extension_id="openai.chatgpt"), extension_id="openai.chatgpt")

    def test_codex_checks_real_windows_binary_architecture(self):
        filename = "extension/bin/windows-x86_64/codex.exe"
        for machine, valid in ((0x8664, True), (0xAA64, False)):
            with self.subTest(machine=machine):
                package = make_vsix(extension_id="openai.chatgpt", platform="win32-x64",
                                    binaries={filename: pe_header(machine)})
                arguments = {"extension_id": "openai.chatgpt", "actual": "win32-x64",
                             "target": "win32-x64"}
                if valid:
                    self.validate_bytes(package, **arguments)
                else:
                    with self.assertRaises(ValueError):
                        self.validate_bytes(package, **arguments)


class DownloadCleanupTests(OfflineTestCase):
    def make_downloader(self, output, attempts):
        session = mock.MagicMock()
        with mock.patch.object(downloader.requests, "Session", return_value=session):
            instance = downloader.ExtensionDownloader(output, attempts=attempts)
        self.addCleanup(instance.session.close)
        return instance, session

    def test_interrupted_stream_retries_then_removes_partial_and_final_files(self):
        def interrupted(_chunk_size):
            yield b"partial VSIX content"
            raise requests.ConnectionError("simulated connection loss")

        with temporary_directory() as temporary:
            instance, session = self.make_downloader(temporary, attempts=2)
            response = session.get.return_value.__enter__.return_value
            response.iter_content.side_effect = interrupted
            with contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(downloader.time, "sleep") as sleep, \
                    mock.patch.object(downloader.logging, "error"), \
                    self.assertRaises(requests.ConnectionError):
                instance.download_build("example.plugin", {"version": "1.0.0",
                                        "targetPlatform": "linux-x64"}, "linux-x64")
            self.assertEqual(session.get.call_count, 2)
            sleep.assert_called_once()
            self.assertFalse(list(Path(temporary).rglob("*.part")))
            self.assertFalse(list(Path(temporary).rglob("*.vsix")))

    def test_failed_package_validation_does_not_publish_a_final_file(self):
        with temporary_directory() as temporary:
            instance, session = self.make_downloader(temporary, attempts=1)
            response = session.get.return_value.__enter__.return_value
            response.iter_content.return_value = [make_vsix(platform="win32-x64")]
            with contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(downloader.logging, "error"), self.assertRaises(ValueError):
                instance.download_build("example.plugin", {"version": "1.0.0",
                                        "targetPlatform": "linux-x64"}, "linux-x64")
            self.assertFalse(list(Path(temporary).rglob("*.part")))
            self.assertFalse(list(Path(temporary).rglob("*.vsix")))

    def test_valid_download_is_published_then_reused_only_after_validation(self):
        with temporary_directory() as temporary:
            instance, session = self.make_downloader(temporary, attempts=1)
            content = make_vsix()
            session.get.return_value.__enter__.return_value.iter_content.return_value = [content]
            build = {"version": "1.0.0", "targetPlatform": "linux-x64"}
            with contextlib.redirect_stdout(io.StringIO()):
                path, metadata, status = instance.download_build("example.plugin", build, "linux-x64")
                _, reused_metadata, reused_status = instance.download_build("example.plugin", build, "linux-x64")
            self.assertEqual(status, "downloaded")
            self.assertEqual(reused_status, "existing")
            self.assertEqual(metadata, reused_metadata)
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(session.get.call_count, 1)
            self.assertEqual(session.get.call_args.kwargs["params"], {"targetPlatform": "linux-x64"})
            self.assertFalse(list(Path(temporary).rglob("*.part")))


if __name__ == "__main__":
    unittest.main()
