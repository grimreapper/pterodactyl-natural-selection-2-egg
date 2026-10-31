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
