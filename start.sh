#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_ROOT="${SERVER_ROOT:-/home/container}"
cd "$SERVER_ROOT"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_uint() {
    local name="$1" value="$2" min="$3" max="$4" normalized LC_ALL=C
    (( ${#value} <= 20 )) || fail "$name must be between $min and $max."
    [[ "$value" =~ ^[0-9]+$ ]] || fail "$name must be an integer."
    normalized="${value#"${value%%[!0]*}"}"
    [[ -n "$normalized" ]] || normalized=0
    if (( ${#normalized} < ${#min} )) || \
        { (( ${#normalized} == ${#min} )) && [[ "$normalized" < "$min" ]]; }; then
        fail "$name must be between $min and $max."
    fi
    if (( ${#normalized} > ${#max} )) || \
        { (( ${#normalized} == ${#max} )) && [[ "$normalized" > "$max" ]]; }; then
        fail "$name must be between $min and $max."
    fi
    printf -v "$name" '%s' "$normalized"
}

has_unsafe_text() {
    local value="$1" LC_ALL=C
    [[ "$value" =~ [[:cntrl:]] || "$value" == *'"'* || "$value" == *'\'* ]]
}

validate_app_manifest() {
    local path="$1"
    local expected_appid="$2"
    LC_ALL=C awk -v expected_appid="$expected_appid" '
        function record_key(key, value, normalized) {
            normalized = tolower(key)
            if (normalized == "appid") {
                appid_total++
                if (depth == 1) {
                    appid_top++
                    appid_value = value
                }
            } else if (normalized == "stateflags") {
                stateflags_total++
                if (depth == 1) {
                    stateflags_top++
                    stateflags_value = value
                }
            }
        }
        function string_token(value, key) {
            if (finished || invalid) {
                invalid = 1
                return
            }
            if (!pending) {
                pending_key = value
                pending = 1
                return
            }
            key = pending_key
            pending_key = ""
            pending = 0
            if (depth == 0) {
                invalid = 1
                return
            }
            record_key(key, value)
        }
        function open_object(key) {
            if (finished || invalid || !pending) {
                invalid = 1
                return
            }
            key = pending_key
            pending_key = ""
            pending = 0
            record_key(key, "")
            if (depth == 0) {
                if (root_seen || tolower(key) != "appstate") {
                    invalid = 1
                    return
                }
                root_seen = 1
            }
            depth++
        }
        function close_object() {
            if (invalid || pending || depth <= 0) {
                invalid = 1
                return
            }
            depth--
            if (depth == 0) finished = 1
        }
        BEGIN {
            depth = 0
            pending_key = ""
            pending = 0
            root_seen = 0
            finished = 0
            invalid = 0
            appid_total = 0
            appid_top = 0
            appid_value = ""
            stateflags_total = 0
            stateflags_top = 0
            stateflags_value = ""
        }
        {
            line = $0
            length_line = length(line)
            index_line = 1
            while (index_line <= length_line && !invalid) {
                character = substr(line, index_line, 1)
                next_character = substr(line, index_line + 1, 1)
                if (character ~ /[[:space:]]/) {
                    index_line++
                } else if (character == "/" && next_character == "/") {
                    break
                } else if (character == "{") {
                    open_object()
                    index_line++
                } else if (character == "}") {
                    close_object()
                    index_line++
                } else if (character == "\"") {
                    value = ""
                    closed_quote = 0
                    index_line++
                    while (index_line <= length_line) {
                        character = substr(line, index_line, 1)
                        if (character == "\\") {
                            index_line++
                            if (index_line > length_line) {
                                invalid = 1
                                break
                            }
                            escaped = substr(line, index_line, 1)
                            if (escaped == "\"" || escaped == "\\") {
                                value = value escaped
                            } else if (escaped == "n") {
                                value = value "\n"
                            } else if (escaped == "t") {
                                value = value "\t"
                            } else {
                                invalid = 1
                                break
                            }
                            index_line++
                        } else if (character == "\"") {
                            closed_quote = 1
                            index_line++
                            break
                        } else {
                            value = value character
                            index_line++
                        }
                    }
                    if (!closed_quote) invalid = 1
                    if (!invalid) string_token(value)
                } else {
                    invalid = 1
                }
            }
        }
        END {
            exit !(invalid == 0 && root_seen == 1 && finished == 1 && depth == 0 && pending == 0 && appid_total == 1 && appid_top == 1 && appid_value == expected_appid && stateflags_total == 1 && stateflags_top == 1 && stateflags_value == "4")
        }
    ' "$path"
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
    (( ${#MOD_IDS} <= 512 )) || fail "MOD_IDS is limited to 512 characters."
    [[ "$MOD_IDS" =~ ^[0-9A-Fa-f]+([ ][0-9A-Fa-f]+)*$ ]] || fail "MOD_IDS must be space-separated hexadecimal Workshop IDs."
    read -r -a mod_tokens <<< "$MOD_IDS"
    MOD_IDS="${mod_tokens[*]}"
fi

[[ -x ./x64/server_linux ]] || fail "Missing executable: x64/server_linux. Reinstall the server."
[[ -f ./steamcmd/linux64/steamclient.so ]] || fail "Missing steamclient.so. Reinstall the server."
[[ -f ./steamapps/appmanifest_4940.acf ]] || fail "Missing steamapps/appmanifest_4940.acf. Reinstall the server."
validate_app_manifest ./steamapps/appmanifest_4940.acf 4940 || fail "Steam manifest must identify app 4940 and mark it fully installed with StateFlags 4 exactly once at the AppState top level. Reinstall the server."

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
