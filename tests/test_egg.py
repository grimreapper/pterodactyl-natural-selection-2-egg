import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EGG = ROOT / "egg-natural-selection-2.json"
START = ROOT / "start.sh"
INSTALL = ROOT / "install.sh"
CHECKSUMS = ROOT / "SHA256SUMS"
ARCHIVE = ROOT / "natural-selection-2-pterodactyl-egg.zip"


def extract_shell_function(source, name):
    marker = f"{name}() {{"
    start = source.index(marker)
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class EggTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egg = json.loads(EGG.read_text())

    def test_ptdl_v2_shape(self):
        self.assertEqual(self.egg["meta"]["version"], "PTDL_v2")
        self.assertEqual(self.egg["startup"], "./start.sh")
        self.assertEqual(
            self.egg["docker_images"]["SteamCMD (Debian)"],
            "ghcr.io/ptero-eggs/steamcmd:debian",
        )
        self.assertEqual(
            self.egg["scripts"]["installation"]["container"],
            "ghcr.io/ptero-eggs/installers:debian",
        )
        envs = [v["env_variable"] for v in self.egg["variables"]]
        self.assertEqual(len(envs), len(set(envs)))
        for required in (
            "SERVER_NAME",
            "MAX_PLAYERS",
            "MAX_SPECTATORS",
            "DEFAULT_MAP",
            "AUTO_UPDATE",
            "SRCDS_APPID",
        ):
            self.assertIn(required, envs)

    def test_native_linux_platform_is_locked(self):
        variables = {item["env_variable"]: item for item in self.egg["variables"]}
        windows_install = variables["WINDOWS_INSTALL"]
        self.assertEqual(windows_install["default_value"], "0")
        self.assertEqual(windows_install["rules"], "required|string|in:0")
        self.assertFalse(windows_install["user_viewable"])
        self.assertFalse(windows_install["user_editable"])

    def test_ptdl_config_fields_are_encoded_json(self):
        expected = {
            "files": {},
            "startup": {"done": "Connected to Steam servers"},
            "logs": {},
        }
        for key, value in expected.items():
            encoded = self.egg["config"][key]
            self.assertIsInstance(encoded, str)
            self.assertEqual(json.loads(encoded), value)
        self.assertEqual(self.egg["config"]["stop"], "^C")

    def test_supported_variable_contract(self):
        variables = {item["env_variable"]: item for item in self.egg["variables"]}
        self.assertEqual(
            set(variables),
            {
                "SERVER_NAME",
                "MAX_PLAYERS",
                "MAX_SPECTATORS",
                "DEFAULT_MAP",
                "SERVER_PASSWORD",
                "MOD_IDS",
                "AUTO_UPDATE",
                "VALIDATE",
                "SRCDS_APPID",
                "STEAM_USER",
                "WINDOWS_INSTALL",
            },
        )
        self.assertEqual(variables["MAX_PLAYERS"]["rules"], "required|integer|between:1,24")
        self.assertEqual(variables["MAX_SPECTATORS"]["rules"], "required|integer|between:0,24")
        self.assertEqual(variables["AUTO_UPDATE"]["rules"], "required|boolean")
        self.assertEqual(variables["VALIDATE"]["rules"], "required|boolean")
        self.assertEqual(variables["SRCDS_APPID"]["rules"], "required|string|in:4940")
        self.assertEqual(variables["STEAM_USER"]["rules"], "required|string|in:anonymous")

    def test_text_artifacts_are_lf_only(self):
        for name in (
            "egg-natural-selection-2.json",
            "install.sh",
            "start.sh",
            "build_artifacts.py",
            "README.md",
            "SHA256SUMS",
            "tests/test_egg.py",
        ):
            self.assertNotIn(b"\r", (ROOT / name).read_bytes(), name)

    def test_public_metadata_is_privacy_safe(self):
        self.assertEqual(self.egg["author"], "community@example.invalid")
        metadata = "\n".join(
            (self.egg["name"], self.egg["author"], self.egg["description"])
        )
        self.assertNotIn("/home/", metadata)
        self.assertNotIn("192.168.", metadata)
        self.assertNotIn("10.0.", metadata)

    def test_embedded_installer_matches_standalone(self):
        self.assertEqual(self.egg["scripts"]["installation"]["script"], INSTALL.read_text())

    def test_embedded_start_script_matches_standalone(self):
        text = INSTALL.read_text()
        marker = "cat > \"$SERVER_DIR/start.sh\" <<'NS2_START_SCRIPT'\n"
        embedded = text.split(marker, 1)[1].split("NS2_START_SCRIPT\n", 1)[0]
        self.assertEqual(embedded, START.read_text())

    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", START], check=True)
        subprocess.run(["bash", "-n", INSTALL], check=True)

    def test_installer_pins_and_verifies_steamcmd_archive(self):
        text = INSTALL.read_text()
        self.assertIn(
            "STEAMCMD_URL=https://media.steampowered.com/client/steamcmd_linux.tar.gz",
            text,
        )
        self.assertIn(
            "STEAMCMD_SHA256=cebf0046bfd08cf45da6bc094ae47aa39ebf4155e5ede41373b579b8f1071e7c",
            text,
        )
        self.assertIn("STEAMCMD_SIZE=2428561", text)
        self.assertIn("--retry-all-errors", text)
        self.assertIn("--max-filesize \"$STEAMCMD_SIZE\"", text)
        self.assertIn("stat -c %s \"$STEAMCMD_ARCHIVE\"", text)
        self.assertIn("sha256sum --check --status", text)
        self.assertIn('tar --no-same-owner -xzf "$STEAMCMD_ARCHIVE"', text)
        self.assertLess(
            text.index("sha256sum --check --status"),
            text.index('tar --no-same-owner -xzf "$STEAMCMD_ARCHIVE"'),
        )

    def test_installer_requires_complete_app_manifest(self):
        installer_only = INSTALL.read_text().split(
            'cat > "$SERVER_DIR/start.sh"', 1
        )[0]
        self.assertIn('"$SERVER_DIR/steamapps/appmanifest_4940.acf"', installer_only)
        self.assertIn("validate_app_manifest() {", installer_only)
        self.assertIn(
            'validate_app_manifest "$SERVER_DIR/steamapps/appmanifest_4940.acf" 4940',
            installer_only,
        )
        self.assertNotIn("grep -E", installer_only)

    def _run_manifest_validator(self, source_path, contents):
        with tempfile.TemporaryDirectory() as td:
            manifest = pathlib.Path(td) / "appmanifest_4940.acf"
            manifest.write_text(contents)
            validator = extract_shell_function(
                source_path.read_text(), "validate_app_manifest"
            )
            script = (
                "set -euo pipefail\n"
                f"{validator}\n"
                'validate_app_manifest "$1" 4940\n'
            )
            return subprocess.run(
                ["bash", "-c", script, "manifest-validator", str(manifest)],
                text=True,
                capture_output=True,
            )

    def test_installer_and_runtime_use_identical_manifest_validator(self):
        installer_only = INSTALL.read_text().split(
            'cat > "$SERVER_DIR/start.sh"', 1
        )[0]
        installer_validator = extract_shell_function(
            installer_only, "validate_app_manifest"
        )
        runtime_validator = extract_shell_function(
            START.read_text(), "validate_app_manifest"
        )
        self.assertEqual(installer_validator, runtime_validator)

    def test_manifest_validators_accept_canonical_case_and_documented_escapes(self):
        manifests = (
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n}\n',
            '"APPSTATE"\n{\n    "APPID" "4940"\n    "stateflags" "4"\n}\n',
            '"AppState"\n{\n'
            '    // Documented VDF escapes in unrelated metadata are valid.\n'
            '    "appid" "4940"\n'
            '    "StateFlags" "4"\n'
            '    "Note" "quote: \\" slash: \\\\ line\\n tab\\t"\n'
            '}\n',
            '"AppState" // token boundaries may cross comments and lines\n{\n'
            '    "appid" // value follows on the next line\n'
            '    "4940"\n'
            '    "StateFlags"\n'
            '    // value follows after a comment-only line\n'
            '    "4"\n}\n',
        )
        for source_path in (INSTALL, START):
            for contents in manifests:
                with self.subTest(source=source_path.name, contents=contents):
                    run = self._run_manifest_validator(source_path, contents)
                    self.assertEqual(run.returncode, 0, run.stderr)

    def test_manifest_validators_reject_adversarial_vdf(self):
        attacks = (
            "",
            '"WrongRoot"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "Nested"\n    {\n'
            '        "appid" "4940"\n        "StateFlags" "4"\n    }\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "appid" "4940"\n'
            '    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n'
            '    "STATEFLAGS" // duplicate split around a comment\n'
            '    "2"\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n'
            '    "Nested" { "APPID" "4940" }\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n'
            '    "Nested" { "stateflags" "4" }\n}\n',
            '"AppState"\n{\n    "appid" "9999"\n    "StateFlags" "4"\n'
            '    "Nested" { "appid" "4940" }\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "2"\n'
            '    "Nested" { "StateFlags" "4" }\n}\n',
            '"AppState"\n{\n    "appid" "04940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "appid" "+4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "appid" "4940 "\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "04"\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4 "\n}\n',
            '"AppState"\n{\n    appid "4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "app" // key splitting must not form appid\n'
            '    "id" "4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "app\\id" "4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n'
            '    "UnknownEscape" "reject\\qthis"\n}\n',
            '"junk" "value"\n'
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n}\n',
            '"AppState"\n{\n    "" "appid" "4940" "StateFlags" "4" ""\n}\n',
            '"AppState"\n{\n    "Nested" { "brace" "}"\n'
            '        "appid" "4940"\n        "StateFlags" "4"\n'
            '        "restore" "{" }\n}\n',
            '"AppState" { "appid" "4940" "StateFlags" "4" }\n'
            '"AppState" { "other" "root" }\n',
            '"AppState"\n{\n    "appid" "4940"\n    "StateFlags" "4"\n',
        )
        for source_path in (INSTALL, START):
            for contents in attacks:
                with self.subTest(source=source_path.name, contents=contents):
                    run = self._run_manifest_validator(source_path, contents)
                    self.assertNotEqual(run.returncode, 0, contents)

    def test_installer_limits_ownership_changes_to_server_directory(self):
        text = INSTALL.read_text()
        self.assertIn('SERVER_DIR="/mnt/server"', text)
        self.assertNotIn("${SERVER_DIR", text)
        self.assertNotIn("chown -R root:root /mnt\n", text)
        self.assertIn('chown -R root:root "$SERVER_DIR"', text)

    def test_release_rebuild_is_independent_of_wall_clock_time(self):
        source_files = (
            "build_artifacts.py",
            "start.sh",
            "egg-natural-selection-2.json",
            "README.md",
            "LICENSE",
            "tests/test_egg.py",
        )
        with tempfile.TemporaryDirectory() as td:
            copy = pathlib.Path(td)
            (copy / "tests").mkdir()
            for name in source_files:
                destination = copy / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, destination)

            subprocess.run(["python3", "build_artifacts.py"], cwd=copy, check=True)
            first = {
                name: (copy / name).read_bytes()
                for name in (
                    "egg-natural-selection-2.json",
                    "SHA256SUMS",
                    "natural-selection-2-pterodactyl-egg.zip",
                )
            }
            first_second = int(time.time())
            while int(time.time()) == first_second:
                time.sleep(0.05)
            subprocess.run(["python3", "build_artifacts.py"], cwd=copy, check=True)
            second = {name: (copy / name).read_bytes() for name in first}
            self.assertEqual(first, second)

    def test_export_timestamp_has_fixed_fallback_and_source_date_override(self):
        source_files = (
            "build_artifacts.py",
            "start.sh",
            "README.md",
            "LICENSE",
            "tests/test_egg.py",
        )
        with tempfile.TemporaryDirectory() as td:
            copy = pathlib.Path(td)
            (copy / "tests").mkdir()
            for name in source_files:
                destination = copy / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, destination)
            env = os.environ.copy()
            env.pop("SOURCE_DATE_EPOCH", None)
            subprocess.run(
                ["python3", "build_artifacts.py"], cwd=copy, env=env, check=True
            )
            generated = json.loads((copy / "egg-natural-selection-2.json").read_text())
            self.assertEqual(generated["exported_at"], "1970-01-01T00:00:00Z")

            env["SOURCE_DATE_EPOCH"] = "1"
            subprocess.run(
                ["python3", "build_artifacts.py"], cwd=copy, env=env, check=True
            )
            generated = json.loads((copy / "egg-natural-selection-2.json").read_text())
            self.assertEqual(generated["exported_at"], "1970-01-01T00:00:01Z")

    def test_checksum_manifest_covers_release_payload(self):
        checksums = {
            name: digest
            for digest, name in (
                line.split("  ", 1) for line in CHECKSUMS.read_text().splitlines()
            )
        }
        self.assertEqual(
            set(checksums),
            {
                "egg-natural-selection-2.json",
                "install.sh",
                "start.sh",
                "README.md",
                "LICENSE",
                "build_artifacts.py",
                "tests/test_egg.py",
            },
        )
        for name, digest in checksums.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_release_archive_matches_worktree_payload(self):
        expected = {
            "egg-natural-selection-2.json",
            "install.sh",
            "start.sh",
            "README.md",
            "LICENSE",
            "build_artifacts.py",
            "tests/test_egg.py",
            "SHA256SUMS",
        }
        with zipfile.ZipFile(ARCHIVE) as archive:
            self.assertEqual(set(archive.namelist()), expected)
            self.assertTrue(
                all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
            )
            for name in expected:
                self.assertEqual(archive.read(name), (ROOT / name).read_bytes(), name)

    def _fake_root(self, td):
        root = pathlib.Path(td)
        (root / "x64").mkdir(parents=True)
        (root / "steamcmd/linux64").mkdir(parents=True)
        (root / "steamapps").mkdir(parents=True)
        (root / "steamcmd/linux64/steamclient.so").write_bytes(b"fake")
        (root / "steamapps/appmanifest_4940.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"4940"\n\t"StateFlags"\t\t"4"\n}\n'
        )
        fake = root / "x64/server_linux"
        fake.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n")
        fake.chmod(0o755)
        return root

    def test_startup_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(
                SERVER_ROOT=str(root),
                SERVER_PORT="29915",
                SERVER_NAME="Test NS2 Server",
                MAX_PLAYERS="18",
                MAX_SPECTATORS="3",
                DEFAULT_MAP="ns2_veil",
                SERVER_PASSWORD="",
                MOD_IDS="706D242 812F004",
            )
            run = subprocess.run([START], env=env, text=True, capture_output=True, check=True)
            out = run.stdout.splitlines()
            self.assertIn("-port", out)
            self.assertIn("29915", out)
            self.assertIn("-map", out)
            self.assertIn("ns2_veil", out)
            self.assertIn("-limit", out)
            self.assertIn("18", out)
            self.assertIn("-mods", out)
            self.assertIn("706D242 812F004", out)
            self.assertNotIn("-password", out)

    def test_startup_numeric_ranges(self):
        cases = (
            ("SERVER_PORT", "1023", False),
            ("SERVER_PORT", "1024", True),
            ("SERVER_PORT", "01024", True),
            ("SERVER_PORT", "65534", True),
            ("SERVER_PORT", "65535", False),
            ("SERVER_PORT", "18446744073709552640", False),
            ("MAX_PLAYERS", "0", False),
            ("MAX_PLAYERS", "1", True),
            ("MAX_PLAYERS", "24", True),
            ("MAX_PLAYERS", "00024", True),
            ("MAX_PLAYERS", "25", False),
            ("MAX_PLAYERS", "18446744073709551617", False),
            ("MAX_SPECTATORS", "-1", False),
            ("MAX_SPECTATORS", "0", True),
            ("MAX_SPECTATORS", "24", True),
            ("MAX_SPECTATORS", "25", False),
            ("MAX_SPECTATORS", "18446744073709551616", False),
        )
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            for name, value, accepted in cases:
                with self.subTest(name=name, value=value):
                    env = os.environ.copy()
                    env.update(SERVER_ROOT=str(root), SERVER_PORT="29915")
                    env[name] = value
                    run = subprocess.run([START], env=env, capture_output=True)
                    self.assertEqual(run.returncode == 0, accepted)

    def test_startup_rejects_long_leading_zero_input_in_bounded_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(
                SERVER_ROOT=str(root),
                SERVER_PORT="29915",
                MAX_PLAYERS="0" * 30000 + "24",
            )
            run = subprocess.run(
                [START], env=env, text=True, capture_output=True, timeout=2
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("between", run.stderr)

    def test_invalid_map_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(SERVER_ROOT=str(root), SERVER_PORT="29915", DEFAULT_MAP="../../bad")
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("DEFAULT_MAP", run.stderr)

    def test_mod_ids_reject_embedded_newline(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(
                SERVER_ROOT=str(root),
                SERVER_PORT="29915",
                MOD_IDS="706D242\n812F004",
            )
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("MOD_IDS", run.stderr)

    def test_mod_ids_reject_more_than_512_characters(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(
                SERVER_ROOT=str(root),
                SERVER_PORT="29915",
                MOD_IDS="A" * 513,
            )
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("512", run.stderr)

    def test_server_name_rejects_ascii_control_characters(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(
                SERVER_ROOT=str(root),
                SERVER_PORT="29915",
                SERVER_NAME="Unsafe\x07Name",
            )
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("control characters", run.stderr)

    def test_text_inputs_reject_single_backslashes(self):
        cases = (
            ("SERVER_NAME", "Unsafe\\Name"),
            ("SERVER_PASSWORD", "Unsafe\\Password"),
        )
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            for name, value in cases:
                with self.subTest(name=name):
                    env = os.environ.copy()
                    env.update(SERVER_ROOT=str(root), SERVER_PORT="29915")
                    env[name] = value
                    run = subprocess.run([START], env=env, text=True, capture_output=True)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("backslashes", run.stderr)

    def test_startup_rejects_missing_app_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            (root / "steamapps/appmanifest_4940.acf").unlink()
            env = os.environ.copy()
            env.update(SERVER_ROOT=str(root), SERVER_PORT="29915")
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("appmanifest_4940.acf", run.stderr)

    def test_startup_rejects_wrong_app_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            (root / "steamapps/appmanifest_4940.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"9999"\n\t"StateFlags"\t\t"4"\n}\n'
            )
            env = os.environ.copy()
            env.update(SERVER_ROOT=str(root), SERVER_PORT="29915")
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("app 4940", run.stderr)

    def test_startup_rejects_incomplete_app_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            (root / "steamapps/appmanifest_4940.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"4940"\n\t"StateFlags"\t\t"2"\n}\n'
            )
            env = os.environ.copy()
            env.update(SERVER_ROOT=str(root), SERVER_PORT="29915")
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("fully installed", run.stderr)

if __name__ == "__main__":
    unittest.main()
