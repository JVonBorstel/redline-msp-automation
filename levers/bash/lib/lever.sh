# Shared helpers for bash levers (B-66). Sourced by a vetted script; never run on its own.
#
# Contract with the Python bridge (core/levers/bridge.py, BashBridge):
#   - the script gets at most one argument, `--what-if` (dry-run); anything else is a usage error (exit 2);
#   - one lever-request JSON line arrives on stdin; the bridge wrote it in a fixed shape, with every string value
#     limited to [A-Za-z0-9._:@+-], so it is read with one anchored pattern match, never by a shell evaluation;
#   - one lever-result JSON line goes to stdout and nothing else; exit 0 = ok, 1 = denied or error, 2 = usage.
# Parameters are data: they are never put in a command line, never evaluated and never used as a path. The functions
# here use only bash builtins (3.2 compatible, so macOS /bin/bash works) and take no command from a parameter.
# Do not call lever_fail or lever_emit inside $( ): they exit, and a subshell would swallow the exit.

set -u
set -o pipefail

LEVER_NAME=""
LEVER_CLIENT=""
LEVER_MODE=""
LEVER_PARAMS=""
LEVER_WHAT_IF=0
LEVER_HOST=""

_lever_usage() {
    printf '{"status":"error","reason":"%s","lever":"unknown","client":"unknown","mode":"unknown","data":null,"diff":[],"applied":false}\n' "$1"
    exit 2
}

# lever_init "$@": parse the one allowed flag, read and check the request line.
lever_init() {
    local arg
    for arg in "$@"; do
        case "$arg" in
            --what-if) LEVER_WHAT_IF=1 ;;
            *) _lever_usage "unknown argument; only --what-if is accepted; nothing ran" ;;
        esac
    done
    local line=""
    IFS= read -r -t 5 line || [[ -n "$line" ]] || _lever_usage "no request on stdin; nothing ran"
    line=${line%$'\r'}
    local re='^\{"version":1,"request_id":"[A-Za-z0-9][A-Za-z0-9._:-]{7,63}","lever":"([a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+)","lever_version":[0-9]+,"client":"([a-z0-9][a-z0-9-]{0,62})","mode":"(dry-run|execute)"(,"as_of":"[0-9T:Z-]+")?,"params":\{([^{}]*)\}\}$'
    [[ "$line" =~ $re ]] || _lever_usage "the request is not a valid lever request; nothing ran"
    LEVER_NAME=${BASH_REMATCH[1]}
    LEVER_CLIENT=${BASH_REMATCH[3]}
    LEVER_MODE=${BASH_REMATCH[4]}
    LEVER_PARAMS=${BASH_REMATCH[6]}
    if [[ "$LEVER_MODE" == "dry-run" && $LEVER_WHAT_IF -ne 1 ]] || [[ "$LEVER_MODE" == "execute" && $LEVER_WHAT_IF -eq 1 ]]; then
        _lever_usage "the request mode and the --what-if flag disagree; nothing ran"
    fi
}

# lever_param NAME: print the value of one parameter (strings without their quotes). Returns 1 if absent.
# NAME comes from the script's own code, never from the request.
lever_param() {
    local re="(^|,)\"$1\":(\"([^\"]*)\"|-?[0-9]+|true|false)(,|\$)"
    [[ "$LEVER_PARAMS" =~ $re ]] || return 1
    local value=${BASH_REMATCH[2]}
    value=${value#\"}
    value=${value%\"}
    printf '%s' "$value"
}

# lever_emit STATUS REASON DATA_JSON DIFF_JSON APPLIED(true|false): print the one result line and exit.
lever_emit() {
    local status=$1 reason=$2 data=$3 diff=$4 applied=$5
    printf '{"status":"%s","reason":"%s","lever":"%s","client":"%s","mode":"%s","data":%s,"diff":%s,"applied":%s}\n' \
        "$status" "$reason" "$LEVER_NAME" "$LEVER_CLIENT" "$LEVER_MODE" "$data" "$diff" "$applied"
    if [[ "$status" == "ok" ]]; then exit 0; fi
    exit 1
}

lever_fail() {
    lever_emit error "$1" null '[]' false
}

# lever_find_host: set LEVER_HOST to the synthetic host state of this call's one client; fail if it has none.
lever_find_host() {
    local root=${REDLINE_UNIX_MOCK_DIR:-}
    if [[ -z "$root" || ! -d "$root/$LEVER_CLIENT" ]]; then
        lever_fail "no mock unix host for client $LEVER_CLIENT; nothing was read"
    fi
    LEVER_HOST="$root/$LEVER_CLIENT"
}
