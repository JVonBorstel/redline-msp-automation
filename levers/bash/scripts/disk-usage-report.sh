#!/usr/bin/env bash
# Lever unix.disk-usage (read): report used space per mount of the client's one mock unix host (B-66).
# Read-only. Mock data: <mock dir>/<client>/disk.tsv, tab separated "mount size_kb used_kb". No command is run.
. "${BASH_SOURCE[0]%/*}/../lib/lever.sh"
lever_init "$@"

threshold=80
if value=$(lever_param threshold_pct); then
    case "$value" in
        '' | *[!0-9]*) lever_fail "threshold_pct must be a whole number from 1 to 100; nothing was read" ;;
    esac
    if ((${#value} > 3)); then lever_fail "threshold_pct must be a whole number from 1 to 100; nothing was read"; fi
    threshold=$((10#$value))
    if ((threshold < 1 || threshold > 100)); then
        lever_fail "threshold_pct must be a whole number from 1 to 100; nothing was read"
    fi
fi

lever_find_host
if [[ ! -f "$LEVER_HOST/disk.tsv" ]]; then lever_fail "the mock host has no disk table; nothing was read"; fi

mounts=""
over=0
while IFS=$'\t' read -r mount size used || [[ -n "$mount" ]]; do
    used=${used%$'\r'}
    if [[ -z "$mount" ]]; then continue; fi
    if [[ ! "$mount" =~ ^/[A-Za-z0-9._/-]*$ || ! "$size" =~ ^[0-9]+$ || ! "$used" =~ ^[0-9]+$ || "$size" -le 0 ]]; then
        lever_fail "a line of the mock disk table is malformed; nothing was reported"
    fi
    pct=$((used * 100 / size))
    flag=false
    if ((pct >= threshold)); then
        flag=true
        over=$((over + 1))
    fi
    mounts="${mounts:+$mounts,}{\"mount\":\"$mount\",\"size_kb\":$size,\"used_kb\":$used,\"used_pct\":$pct,\"over_threshold\":$flag}"
done <"$LEVER_HOST/disk.tsv"

lever_emit ok "disk usage read" "{\"threshold_pct\":$threshold,\"over_threshold\":$over,\"mounts\":[$mounts]}" '[]' false
