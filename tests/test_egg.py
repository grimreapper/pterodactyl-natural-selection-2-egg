import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EGG = ROOT / "egg-natural-selection-2.json"
START = ROOT / "start.sh"
INSTALL = ROOT / "install.sh"


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

    def _fake_root(self, td):
        root = pathlib.Path(td)
        (root / "x64").mkdir(parents=True)
        (root / "steamcmd/linux64").mkdir(parents=True)
        (root / "steamcmd/linux64/steamclient.so").write_bytes(b"fake")
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

    def test_invalid_map_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fake_root(td)
            env = os.environ.copy()
            env.update(SERVER_ROOT=str(root), SERVER_PORT="29915", DEFAULT_MAP="../../bad")
            run = subprocess.run([START], env=env, text=True, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("DEFAULT_MAP", run.stderr)

if __name__ == "__main__":
    unittest.main()
