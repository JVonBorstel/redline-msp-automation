#!/usr/bin/env bash
# Lever unix.clear-cache (write): delete the plain files in one allowlisted cache folder of the client's mock unix
# host (B-66). Only direct children that are regular files with a plain name are removed; folders, links and odd
# names are left and counted. The names come from the folder listing, never from a parameter. With --what-if the
# same diff is reported and nothing is deleted.
. "${BASH_SOURCE[0]%/*}/../lib/lever.sh"
lever_init "$@"

scope=""
if ! scope=$(lever_param scope); then lever_fail "param scope is required; nothing ran"; fi
case "$scope" in
    user-cache | app-cache) ;;
    *) lever_fail "scope must be user-cache or app-cache; nothing ran" ;;
esac

lever_find_host
folder="$LEVER_HOST/cache/$scope"
if [[ ! -d "$folder" || -L "$folder" ]]; then lever_fail "the mock host has no $scope folder; nothing ran"; fi

diff=""
files=0
bytes=0
skipped=0
doomed=()
for path in "$folder"/*; do
    if [[ ! -e "$path" && ! -L "$path" ]]; then continue; fi
    name=${path##*/}
    if [[ -L "$path" || ! -f "$path" || ! "$name" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
        skipped=$((skipped + 1))
        continue
    fi
    size=$(wc -c <"$path")
    size=${size// /}
    files=$((files + 1))
    bytes=$((bytes + size))
    doomed+=("$path")
    diff="${diff:+$diff,}{\"op\":\"remove\",\"path\":\"/cache/$scope/$name\",\"before\":{\"size_bytes\":$size},\"after\":null}"
done
data="{\"scope\":\"$scope\",\"files\":$files,\"bytes\":$bytes,\"skipped\":$skipped}"

if ((LEVER_WHAT_IF == 1)); then
    lever_emit ok "dry-run: nothing applied" "$data" "[$diff]" false
fi
if ((files == 0)); then
    lever_emit ok "no change: already in the desired state" "$data" '[]' false
fi
for path in "${doomed[@]}"; do
    if ! rm -f -- "$path"; then lever_fail "a cache file could not be removed; nothing more was removed"; fi
done
lever_emit ok "cache cleared" "$data" "[$diff]" true
