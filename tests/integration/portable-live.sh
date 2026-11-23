#!/usr/bin/env bash
# Real restic exercise for ISO export and a fully standalone access script.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Must be root" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d /tmp/hangar-portable-test.XXXXXXXX)"
trap 'rm -rf "$work"; rm -f /etc/hangar/repos/portable-ci.json /etc/hangar/repos/portable-ci.key' EXIT
mkdir -p /etc/hangar/repos /usr/libexec/hangar /var/cache/hangar/restic
install -m 0755 "$ROOT/libexec/hangar-run" /usr/libexec/hangar/hangar-run
install -m 0755 "$ROOT/libexec/hangar-portable" /usr/libexec/hangar/hangar-portable
install -m 0755 "$ROOT/libexec/hangar-vhd" /usr/libexec/hangar/hangar-vhd
printf '%s' 'portable-test-secret' > /etc/hangar/repos/portable-ci.key
chmod 600 /etc/hangar/repos/portable-ci.key
mkdir -p "$work/repo" "$work/input"
printf '%s\n' 'snapshot ISO standalone round trip' > "$work/input/example.txt"
ln -s example.txt "$work/input/link.txt"
printf '{"id":"portable-ci","kind":"local","path":"%s"}\n' "$work/repo" > /etc/hangar/repos/portable-ci.json
key=/etc/hangar/repos/portable-ci.key
restic -r "$work/repo" --password-file "$key" init
restic -r "$work/repo" --password-file "$key" backup "$work/input"
snapshot="$(restic -r "$work/repo" --password-file "$key" snapshots --json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"

# Cockpit's ISO action works.
python3 /usr/libexec/hangar/hangar-portable iso portable-ci "$snapshot" "$work/hangar.iso"
test -s "$work/hangar.iso"

# The key and script are generated beside an existing repository, retroactively.
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
test -f "$work/repo/hangar-access.key"
test -x "$work/repo/hangar-access.sh"
test -f "$work/repo/hangar-vhd.py"
"$work/repo/hangar-access.sh" snapshots
python3 "$work/repo/hangar-vhd.py" --help >/dev/null

# A generated helper may be updated safely, without overwriting an unknown script.
printf '\n# previous Hangar revision\n' >> "$work/repo/hangar-vhd.py"
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
cmp "$ROOT/libexec/hangar-vhd" "$work/repo/hangar-vhd.py"

# Existing v2 kits must be recognized, migrated without changing their key.
python3 - "$work/repo/hangar-access.sh" <<'PY'
import runpy, sys
from pathlib import Path
old = runpy.run_path("/usr/libexec/hangar/hangar-portable", run_name="hangar_test")
Path(sys.argv[1]).write_text(old["ACCESS_SCRIPT_V2"], encoding="utf-8")
PY
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
grep -q "Hangar standalone access kit v4" "$work/repo/hangar-access.sh"
cmp "$key" "$work/repo/hangar-access.key"

# A generated v3 kit from the previous Hangar release is safe to upgrade.
python3 - "$work/repo/hangar-access.sh" <<'PY'
from pathlib import Path
import runpy
import sys
old = runpy.run_path("/usr/libexec/hangar/hangar-portable", run_name="hangar_test")
Path(sys.argv[1]).write_text(old["ACCESS_SCRIPT_V3"], encoding="utf-8")
PY
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
grep -q "Hangar standalone access kit v4" "$work/repo/hangar-access.sh"
grep -q 'raw' "$work/repo/hangar-access.sh"
cmp "$key" "$work/repo/hangar-access.key"

# Simulate an old kit and upgrade it, WITHOUT replacing or losing its key.
cat > "$work/repo/hangar-access.sh" <<'LEGACY'
#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec restic -r "$here" --password-file "$here/hangar-access.key" "$@"
LEGACY
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
grep -q "Hangar standalone access kit v4" "$work/repo/hangar-access.sh"
cmp "$key" "$work/repo/hangar-access.key"

# Even after removing Hangar's executable, the access-kit shell script works.
mv /usr/libexec/hangar/hangar-portable "$work/portable-away"
mv /usr/libexec/hangar/hangar-run "$work/runner-away"
mv /usr/libexec/hangar/hangar-vhd "$work/builder-away"
"$work/repo/hangar-access.sh" iso latest "$work/standalone.iso"
test -s "$work/standalone.iso"
mkdir "$work/extracted"
xorriso -osirrox on -indev "$work/standalone.iso" -extract / "$work/extracted" >/dev/null 2>&1
cmp "$work/input/example.txt" "$work/extracted$work/input/example.txt"

# ISO building never writes a snapshot or changes the backup history.
count="$(restic -r "$work/repo" --password-file "$key" snapshots --json |
    python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
test "$count" -eq 1
if "$work/repo/hangar-access.sh" iso latest "$work/standalone.iso"; then
    echo "ISO builder must refuse to overwrite existing output" >&2; exit 1
fi
echo "Standalone data ISO, independent VHD helper, and legacy access-kit upgrade passed"
