#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_DIR=/mnt/server
STEAMCMD_URL=https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz

[[ "${SRCDS_APPID:-4940}" == "4940" ]] || { echo "Refusing unexpected app ID." >&2; exit 1; }
mkdir -p "$SERVER_DIR/steamcmd" "$SERVER_DIR/steamapps" "$SERVER_DIR/config" "$SERVER_DIR/logs"

curl --fail --location --silent --show-error --retry 4 --connect-timeout 20 \
    --proto '=https' --tlsv1.2 \
    --url "$STEAMCMD_URL" --output /tmp/steamcmd_linux.tar.gz
tar -xzf /tmp/steamcmd_linux.tar.gz -C "$SERVER_DIR/steamcmd"
rm -f /tmp/steamcmd_linux.tar.gz

chown -R root:root /mnt
export HOME="$SERVER_DIR"
cd "$SERVER_DIR/steamcmd"
./steamcmd.sh \
    +force_install_dir "$SERVER_DIR" \
    +login anonymous \
    +app_info_update 1 \
    +app_update 4940 validate \
    +quit

[[ -x "$SERVER_DIR/x64/server_linux" ]] || { echo "SteamCMD completed without x64/server_linux." >&2; exit 1; }
[[ -f "$SERVER_DIR/steamcmd/linux64/steamclient.so" ]] || { echo "Missing 64-bit steamclient.so." >&2; exit 1; }
mkdir -p "$SERVER_DIR/.steam/sdk64"
cp -f "$SERVER_DIR/steamcmd/linux64/steamclient.so" "$SERVER_DIR/.steam/sdk64/steamclient.so"

if [[ ! -f "$SERVER_DIR/config/MapCycle.json" ]]; then
    cat > "$SERVER_DIR/config/MapCycle.json" <<'NS2_MAP_CYCLE'
{
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
NS2_MAP_CYCLE
fi

cat > "$SERVER_DIR/start.sh" <<'NS2_START_SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_ROOT="${SERVER_ROOT:-/home/container}"
cd "$SERVER_ROOT"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_uint() {
    local name="$1" value="$2" min="$3" max="$4"
    [[ "$value" =~ ^[0-9]+$ ]] || fail "$name must be an integer."
    (( value >= min && value <= max )) || fail "$name must be between $min and $max."
}

has_unsafe_text() {
    local value="$1"
    [[ "$value" == *$'\n'* || "$value" == *$'\r'* || "$value" == *$'\t'* || "$value" == *'"'* || "$value" == *'\\'* ]]
}

SERVER_NAME="${SERVER_NAME-Natural Selection 2 Server}"
MAX_PLAYERS="${MAX_PLAYERS-20}"
MAX_SPECTATORS="${MAX_SPECTATORS-5}"
DEFAULT_MAP="${DEFAULT_MAP-ns2_summit}"
SERVER_PASSWORD="${SERVER_PASSWORD-}"
MOD_IDS="${MOD_IDS-}"

[[ -n "$SERVER_NAME" ]] || fail "SERVER_NAME cannot be empty."
(( ${#SERVER_NAME} <= 80 )) || fail "SERVER_NAME is limited to 80 characters."
has_unsafe_text "$SERVER_NAME" && fail 'SERVER_NAME cannot contain control characters, double quotes, or backslashes.'

require_uint SERVER_PORT "${SERVER_PORT:?SERVER_PORT is required}" 1024 65534
require_uint MAX_PLAYERS "$MAX_PLAYERS" 1 24
require_uint MAX_SPECTATORS "$MAX_SPECTATORS" 0 24
QUERY_PORT=$((SERVER_PORT + 1))

case "$DEFAULT_MAP" in
    ns2_ayumi|ns2_biodome|ns2_caged|ns2_derelict|ns2_descent|ns2_docking|ns2_eclipse|ns2_kodiak|ns2_metro|ns2_mineshaft|ns2_origin|ns2_refinery|ns2_summit|ns2_tanith|ns2_tram|ns2_unearthed|ns2_veil) ;;
    *) fail "DEFAULT_MAP is not one of the 17 maps shipped by app 4940." ;;
esac

if [[ -n "$SERVER_PASSWORD" ]]; then
    (( ${#SERVER_PASSWORD} <= 64 )) || fail "SERVER_PASSWORD is limited to 64 characters."
    has_unsafe_text "$SERVER_PASSWORD" && fail 'SERVER_PASSWORD cannot contain control characters, double quotes, or backslashes.'
fi

if [[ -n "$MOD_IDS" ]]; then
    [[ "$MOD_IDS" =~ ^[0-9A-Fa-f]+([[:space:]]+[0-9A-Fa-f]+)*$ ]] || fail "MOD_IDS must be space-separated hexadecimal Workshop IDs."
    read -r -a mod_tokens <<< "$MOD_IDS"
    MOD_IDS="${mod_tokens[*]}"
fi

[[ -x ./x64/server_linux ]] || fail "Missing executable: x64/server_linux. Reinstall the server."
[[ -f ./steamcmd/linux64/steamclient.so ]] || fail "Missing steamclient.so. Reinstall the server."

mkdir -p .steam/sdk64 config/Workshop logs
ln -sfn "$SERVER_ROOT/steamcmd/linux64/steamclient.so" .steam/sdk64/steamclient.so

export HOME="$SERVER_ROOT"

args=(
    -ip 0.0.0.0
    -name "$SERVER_NAME"
    -port "$SERVER_PORT"
    -map "$DEFAULT_MAP"
    -limit "$MAX_PLAYERS"
    -speclimit "$MAX_SPECTATORS"
    -config_path config
    -logdir logs
    -modstorage config/Workshop
)

[[ -z "$SERVER_PASSWORD" ]] || args+=( -password "$SERVER_PASSWORD" )
[[ -z "$MOD_IDS" ]] || args+=( -mods "$MOD_IDS" )

printf 'Starting Natural Selection 2: game UDP %s, query UDP %s\n' "$SERVER_PORT" "$QUERY_PORT"

exec ./x64/server_linux "${args[@]}"
NS2_START_SCRIPT
chmod 0755 "$SERVER_DIR/start.sh"
bash -n "$SERVER_DIR/start.sh"

echo "Natural Selection 2 app 4940 installed successfully."
