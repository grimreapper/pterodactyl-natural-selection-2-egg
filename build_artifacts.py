#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def resolve_exported_at(path: Path) -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        if not re.fullmatch(r"[0-9]+", source_date_epoch):
            raise SystemExit("SOURCE_DATE_EPOCH must be a non-negative integer")
        try:
            moment = datetime.fromtimestamp(int(source_date_epoch), timezone.utc)
        except (OSError, OverflowError, ValueError) as error:
            raise SystemExit(f"SOURCE_DATE_EPOCH is out of range: {error}") from error
        return moment.isoformat(timespec="seconds").replace("+00:00", "Z")

    if path.is_file():
        try:
            previous = json.loads(path.read_text()).get("exported_at")
        except (json.JSONDecodeError, OSError):
            previous = None
        if isinstance(previous, str) and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            previous,
        ):
            try:
                datetime.strptime(previous, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
            else:
                return previous

    return "1970-01-01T00:00:00Z"


exported_at = resolve_exported_at(ROOT / "egg-natural-selection-2.json")
START = (ROOT / "start.sh").read_text()
if "NS2_START_SCRIPT" in START:
    raise SystemExit("start.sh contains reserved heredoc marker")


def extract_shell_function(source: str, name: str) -> str:
    marker = f"{name}() {{"
    start = source.index(marker)
    end = source.index("\n}\n", start) + 3
    return source[start:end]


MANIFEST_VALIDATOR = extract_shell_function(START, "validate_app_manifest")

MAP_CYCLE = """{
  "time": 30,
  "mode": "order",
  "maps": [
    "ns2_summit",
    "ns2_mineshaft",
    "ns2_tram",
    "ns2_veil",
    "ns2_docking",
    "ns2_descent",
    "ns2_refinery",
    "ns2_biodome",
    "ns2_eclipse",
    "ns2_caged",
    "ns2_kodiak",
    "ns2_derelict",
    "ns2_unearthed",
    "ns2_origin",
    "ns2_tanith",
    "ns2_ayumi",
    "ns2_metro"
  ],
  "mods": []
}
"""

INSTALL_PREFIX = (
    r'''#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_DIR="/mnt/server"
STEAMCMD_URL=https://media.steampowered.com/client/steamcmd_linux.tar.gz
STEAMCMD_SHA256=cebf0046bfd08cf45da6bc094ae47aa39ebf4155e5ede41373b579b8f1071e7c
STEAMCMD_SIZE=2428561
STEAMCMD_ARCHIVE=$(mktemp /tmp/steamcmd_linux.XXXXXX)
trap 'rm -f "$STEAMCMD_ARCHIVE"' EXIT

[[ "${SRCDS_APPID:-4940}" == "4940" ]] || { echo "Refusing unexpected app ID." >&2; exit 1; }
mkdir -p "$SERVER_DIR/steamcmd" "$SERVER_DIR/steamapps" "$SERVER_DIR/config" "$SERVER_DIR/logs"

curl --fail --location --silent --show-error --retry 4 --retry-all-errors --retry-delay 2 --connect-timeout 20 \
    --max-filesize "$STEAMCMD_SIZE" \
    --proto '=https' --tlsv1.2 \
    --url "$STEAMCMD_URL" --output "$STEAMCMD_ARCHIVE"
[[ "$(stat -c %s "$STEAMCMD_ARCHIVE")" == "$STEAMCMD_SIZE" ]] || { echo "SteamCMD archive size mismatch." >&2; exit 1; }
printf '%s  %s\n' "$STEAMCMD_SHA256" "$STEAMCMD_ARCHIVE" | sha256sum --check --status || { echo "SteamCMD archive checksum mismatch." >&2; exit 1; }
tar --no-same-owner -xzf "$STEAMCMD_ARCHIVE" -C "$SERVER_DIR/steamcmd"
rm -f "$STEAMCMD_ARCHIVE"
trap - EXIT

if (( EUID == 0 )); then
    chown -R root:root "$SERVER_DIR"
fi
export HOME="$SERVER_DIR"
cd "$SERVER_DIR/steamcmd"
./steamcmd.sh \
    +force_install_dir "$SERVER_DIR" \
    +login anonymous \
    +app_info_update 1 \
    +app_update 4940 validate \
    +quit
'''
    + "\n"
    + MANIFEST_VALIDATOR
    + r'''
[[ -x "$SERVER_DIR/x64/server_linux" ]] || { echo "SteamCMD completed without x64/server_linux." >&2; exit 1; }
[[ -f "$SERVER_DIR/steamcmd/linux64/steamclient.so" ]] || { echo "Missing 64-bit steamclient.so." >&2; exit 1; }
[[ -f "$SERVER_DIR/steamapps/appmanifest_4940.acf" ]] || { echo "Missing appmanifest_4940.acf." >&2; exit 1; }
validate_app_manifest "$SERVER_DIR/steamapps/appmanifest_4940.acf" 4940 || { echo "Steam manifest must identify app 4940 and mark it fully installed with StateFlags 4 exactly once at the AppState top level." >&2; exit 1; }
mkdir -p "$SERVER_DIR/.steam/sdk64"
cp -f "$SERVER_DIR/steamcmd/linux64/steamclient.so" "$SERVER_DIR/.steam/sdk64/steamclient.so"

if [[ ! -f "$SERVER_DIR/config/MapCycle.json" ]]; then
    cat > "$SERVER_DIR/config/MapCycle.json" <<'NS2_MAP_CYCLE'
'''
)

INSTALL_MIDDLE = r'''NS2_MAP_CYCLE
fi

cat > "$SERVER_DIR/start.sh" <<'NS2_START_SCRIPT'
'''

INSTALL_SUFFIX = r'''NS2_START_SCRIPT
chmod 0755 "$SERVER_DIR/start.sh"
bash -n "$SERVER_DIR/start.sh"

echo "Natural Selection 2 app 4940 installed successfully."
'''

install = INSTALL_PREFIX + MAP_CYCLE + INSTALL_MIDDLE + START + INSTALL_SUFFIX
(ROOT / "install.sh").write_text(install)
os.chmod(ROOT / "install.sh", 0o755)
os.chmod(ROOT / "start.sh", 0o755)

maps = "ns2_ayumi,ns2_biodome,ns2_caged,ns2_derelict,ns2_descent,ns2_docking,ns2_eclipse,ns2_kodiak,ns2_metro,ns2_mineshaft,ns2_origin,ns2_refinery,ns2_summit,ns2_tanith,ns2_tram,ns2_unearthed,ns2_veil"
variables = [
    {
        "name": "Server Name",
        "description": "Name shown in the NS2 server browser. Maximum 80 characters; control characters, double quotes, and backslashes are rejected by the startup wrapper.",
        "env_variable": "SERVER_NAME",
        "default_value": "Natural Selection 2 Server",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|string|max:80",
        "field_type": "text",
    },
    {
        "name": "Maximum Players",
        "description": "Active player slots. The NS2 engine hard limit is 24. The game is mainly single-thread limited; larger servers need high per-core CPU speed.",
        "env_variable": "MAX_PLAYERS",
        "default_value": "20",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|integer|between:1,24",
        "field_type": "text",
    },
    {
        "name": "Spectator Slots",
        "description": "Additional spectator slots. 0 disables dedicated spectator slots; accepted range is 0-24.",
        "env_variable": "MAX_SPECTATORS",
        "default_value": "5",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|integer|between:0,24",
        "field_type": "text",
    },
    {
        "name": "Initial Map",
        "description": f"Initial map. Valid shipped maps: {maps}.",
        "env_variable": "DEFAULT_MAP",
        "default_value": "ns2_summit",
        "user_viewable": True,
        "user_editable": True,
        "rules": f"required|string|in:{maps}",
        "field_type": "text",
    },
    {
        "name": "Server Password",
        "description": "Optional player password. Leave blank for a public server. Maximum 64 characters; control characters, double quotes, and backslashes are rejected.",
        "env_variable": "SERVER_PASSWORD",
        "default_value": "",
        "user_viewable": True,
        "user_editable": True,
        "rules": "nullable|string|max:64",
        "field_type": "text",
    },
    {
        "name": "Workshop Mod IDs",
        "description": "Optional space-separated hexadecimal Workshop IDs for -mods. Example: 706D242. MapCycle.json can also define decimal UGC IDs and per-map mods.",
        "env_variable": "MOD_IDS",
        "default_value": "",
        "user_viewable": True,
        "user_editable": True,
        "rules": "nullable|string|max:512|regex:/^[0-9A-Fa-f]+( [0-9A-Fa-f]+)*$/",
        "field_type": "text",
    },

    {
        "name": "Auto Update",
        "description": "1 updates app 4940 through SteamCMD every time the container starts; 0 starts the installed build without checking Steam.",
        "env_variable": "AUTO_UPDATE",
        "default_value": "1",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|boolean",
        "field_type": "text",
    },
    {
        "name": "Validate on Startup",
        "description": "1 makes SteamCMD validate all app files during each automatic update; 0 performs a normal update check. Validation is slower and may restore changed game files.",
        "env_variable": "VALIDATE",
        "default_value": "0",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|boolean",
        "field_type": "text",
    },
    {
        "name": "Steam App ID",
        "description": "Natural Selection 2 Dedicated Server app ID.",
        "env_variable": "SRCDS_APPID",
        "default_value": "4940",
        "user_viewable": False,
        "user_editable": False,
        "rules": "required|string|in:4940",
        "field_type": "text",
    },
    {
        "name": "Steam User",
        "description": "App 4940 currently installs anonymously; no personal Steam account is required.",
        "env_variable": "STEAM_USER",
        "default_value": "anonymous",
        "user_viewable": False,
        "user_editable": False,
        "rules": "required|string|in:anonymous",
        "field_type": "text",
    },
    {
        "name": "Windows Install",
        "description": "Native Linux server files are required.",
        "env_variable": "WINDOWS_INSTALL",
        "default_value": "0",
        "user_viewable": False,
        "user_editable": False,
        "rules": "required|string|in:0",
        "field_type": "text",
    },
]

egg = {
    "_comment": "DO NOT EDIT: FILE GENERATED AUTOMATICALLY BY PTERODACTYL PANEL - PTERODACTYL.IO",
    "meta": {"version": "PTDL_v2", "update_url": None},
    "exported_at": exported_at,
    "name": "Natural Selection 2",
    "author": "community@example.invalid",
    "description": "Natural Selection 2 native Linux dedicated server (Steam app 4940). Anonymous SteamCMD install, automatic updates, and configurable vanilla maps/mods.",
    "features": ["steam_disk_space"],
    "docker_images": {"SteamCMD (Debian)": "ghcr.io/ptero-eggs/steamcmd:debian"},
    "file_denylist": [],
    "startup": "./start.sh",
    "config": {
        "files": "{}",
        "startup": json.dumps({"done": "Connected to Steam servers"}, indent=4),
        "logs": "{}",
        "stop": "^C",
    },
    "scripts": {
        "installation": {
            "script": install,
            "container": "ghcr.io/ptero-eggs/installers:debian",
            "entrypoint": "bash",
        }
    },
    "variables": variables,
}

(ROOT / "egg-natural-selection-2.json").write_text(json.dumps(egg, indent=4) + "\n")

checksum_files = [
    "egg-natural-selection-2.json",
    "install.sh",
    "start.sh",
    "README.md",
    "LICENSE",
    "build_artifacts.py",
    "tests/test_egg.py",
]
lines = []
for name in checksum_files:
    data = (ROOT / name).read_bytes()
    lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
(ROOT / "SHA256SUMS").write_text("\n".join(lines) + "\n")

archive_files = checksum_files + ["SHA256SUMS"]
archive_path = ROOT / "natural-selection-2-pterodactyl-egg.zip"
executable_files = {"install.sh", "start.sh", "build_artifacts.py"}
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
    for name in archive_files:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        mode = 0o755 if name in executable_files else 0o644
        info.external_attr = (0o100000 | mode) << 16
        archive.writestr(info, (ROOT / name).read_bytes())

print(
    "generated egg-natural-selection-2.json, install.sh, SHA256SUMS, "
    "and natural-selection-2-pterodactyl-egg.zip"
)
