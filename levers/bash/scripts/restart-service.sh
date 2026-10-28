#!/usr/bin/env bash
# Lever unix.restart-service (write): restart one allowlisted service on the client's mock unix host (B-66).
# Mock: bumps the restart counter and sets the state to running in <mock dir>/<client>/services.tsv ("name state
# restarts", tab separated). No systemctl or launchctl is called. With --what-if it reports the same diff and writes nothing.
. "${BASH_SOURCE[0]%/*}/../lib/lever.sh"
lever_init "$@"

service=""
if ! service=$(lever_param service); then lever_fail "param service is required; nothing ran"; fi
case "$service" in
    cups | chronyd | rsyslog) ;;
    *) lever_fail "service is not on the allowlist (cups, chronyd, rsyslog); nothing ran" ;;
esac

lever_find_host
table="$LEVER_HOST/services.tsv"
if [[ ! -f "$table" ]]; then lever_fail "the mock host has no service table; nothing ran"; fi

out=""
diff=""
found=0
while IFS=$'\t' read -r name state restarts || [[ -n "$name" ]]; do
    restarts=${restarts%$'\r'}
    if [[ -z "$name" ]]; then continue; fi
    if [[ ! "$name" =~ ^[a-z][a-z0-9-]{1,31}$ || ! "$state" =~ ^(running|stopped)$ || ! "$restarts" =~ ^[0-9]+$ ]]; then
        lever_fail "a line of the mock service table is malformed; nothing ran"
    fi
    if [[ "$name" == "$service" ]]; then
        found=1
        next=$((restarts + 1))
        diff="{\"op\":\"replace\",\"path\":\"/services/$name/restarts\",\"before\":$restarts,\"after\":$next}"
        if [[ "$state" != "running" ]]; then
            diff="$diff,{\"op\":\"replace\",\"path\":\"/services/$name/state\",\"before\":\"$state\",\"after\":\"running\"}"
        fi
        state=running
        restarts=$next
    fi
    out="$out$name"$'\t'"$state"$'\t'"$restarts"$'\n'
done <"$table"
if ((found != 1)); then lever_fail "service $service is not present on this client's host; nothing ran"; fi

if ((LEVER_WHAT_IF == 1)); then
    lever_emit ok "dry-run: nothing applied" "{\"service\":\"$service\"}" "[$diff]" false
fi
tmp="$table.$$.tmp"
if ! { printf '%s' "$out" >"$tmp" && mv -f -- "$tmp" "$table"; }; then
    rm -f -- "$tmp"
    lever_fail "the service table could not be written; nothing was reported as applied"
fi
lever_emit ok "service restarted" "{\"service\":\"$service\"}" "[$diff]" true
