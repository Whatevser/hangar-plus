#!/usr/bin/env bash
# Real restic round trip for the portable archive backend.
# Run in a disposable Linux environment as root with restic and xorriso.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Must be root" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d /tmp/hangar-portable-test.XXXXXXXX)"
trap 'rm -rf "$work"; rm -f /etc/hangar/repos/portable-ci.json /etc/hangar/repos/portable-ci.key' EXIT
mkdir -p /etc/hangar/repos /usr/libexec/hangar /var/cache/hangar/restic
install -m 0755 "$ROOT/libexec/hangar-run" /usr/libexec/hangar/hangar-run
install -m 0755 "$ROOT/libexec/hangar-portable" /usr/libexec/hangar/hangar-portable
printf '%s' 'portable-test-secret' > /etc/hangar/repos/portable-ci.key
chmod 600 /etc/hangar/repos/portable-ci.key
mkdir -p "$work/repo" "$work/input"
printf '%s\n' 'snapshot ISO and ZIP round trip' > "$work/input/example.txt"
ln -s example.txt "$work/input/link.txt"
printf '{"id":"portable-ci","kind":"local","path":"%s"}\n' "$work/repo" > /etc/hangar/repos/portable-ci.json
key=/etc/hangar/repos/portable-ci.key
restic -r "$work/repo" --password-file "$key" init
restic -r "$work/repo" --password-file "$key" backup "$work/input"
snapshot="$(restic -r "$work/repo" --password-file "$key" snapshots --json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
python3 /usr/libexec/hangar/hangar-portable iso portable-ci "$snapshot" "$work/snapshot.iso"
test -s "$work/snapshot.iso"
python3 /usr/libexec/hangar/hangar-portable import portable-ci "$work/snapshot.iso"
restic -r "$work/repo" --password-file "$key" dump --archive zip "$snapshot:/" / > "$work/snapshot.zip"
test -s "$work/snapshot.zip"
python3 /usr/libexec/hangar/hangar-portable import portable-ci "$work/snapshot.zip"
count="$(restic -r "$work/repo" --password-file "$key" snapshots --json |
    python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
test "$count" -eq 3
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
test -f "$work/repo/hangar-access.key"
test -x "$work/repo/hangar-access.sh"
"$work/repo/hangar-access.sh" snapshots
if python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci; then
    echo "Access kit must refuse to overwrite an existing key" >&2; exit 1
fi
echo "Portable snapshot ISO, ZIP and access-kit round trip passed"
