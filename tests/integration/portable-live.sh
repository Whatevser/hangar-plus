#!/usr/bin/env bash
# Live restic/access-kit exercise without optical-disc export dependencies.
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
printf '%s\n' 'standalone restic/access-kit round trip' > "$work/input/example.txt"
ln -s example.txt "$work/input/link.txt"
printf '{"id":"portable-ci","kind":"local","path":"%s"}\n' "$work/repo" > /etc/hangar/repos/portable-ci.json
key=/etc/hangar/repos/portable-ci.key
restic -r "$work/repo" --password-file "$key" init
restic -r "$work/repo" --password-file "$key" backup "$work/input"

# Access kit can work on a separate recovery host without Cockpit or Hangar.
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
test -f "$work/repo/hangar-access.key"
test -x "$work/repo/hangar-access.sh"
test -f "$work/repo/hangar-vhd.py"
grep -q "Hangar standalone access kit v5" "$work/repo/hangar-access.sh"
! grep -Eqi 'xorriso|iso-level|mkisofs' "$work/repo/hangar-access.sh"
sh -n "$work/repo/hangar-access.sh"
"$work/repo/hangar-access.sh" snapshots
python3 "$work/repo/hangar-vhd.py" --help >/dev/null
mkdir "$work/recovered"
"$work/repo/hangar-access.sh" restore latest --target "$work/recovered"
cmp "$work/input/example.txt" "$work/recovered$work/input/example.txt"

# Independent builder may be updated safely without replacing user scripts.
printf '\n# previous Hangar revision\n' >> "$work/repo/hangar-vhd.py"
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
cmp "$ROOT/libexec/hangar-vhd" "$work/repo/hangar-vhd.py"

# Pre-disk-export restic-only access kits can still be upgraded without
# changing their repository credentials.
cat > "$work/repo/hangar-access.sh" <<'LEGACY'
#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec restic -r "$here" --password-file "$here/hangar-access.key" "$@"
LEGACY
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci
grep -q "Hangar standalone access kit v5" "$work/repo/hangar-access.sh"
cmp "$key" "$work/repo/hangar-access.key"

# A customized wrapper must never be silently overwritten.
printf '\n# custom edit\n' >> "$work/repo/hangar-access.sh"
if python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci; then
    echo "Custom access script must not be replaced" >&2; exit 1
fi
sed -i '$d' "$work/repo/hangar-access.sh"
python3 /usr/libexec/hangar/hangar-portable access-kit portable-ci

# Verify all disk aliases reach the copied Python builder. A fake interpreter
# records dispatch arguments without allocating or modifying any disk image.
mkdir "$work/fake-bin"
cat > "$work/fake-bin/python3" <<'FAKE'
#!/bin/sh
printf '%s\n' "$@" > "$HANGAR_TEST_ARGS"
FAKE
chmod +x "$work/fake-bin/python3"
for ext in raw img vhd vhdx qcow2 vdi vmdk; do
    output="$work/recovery.$ext"
    HANGAR_TEST_ARGS="$work/args" PATH="$work/fake-bin:$PATH" \
        "$work/repo/hangar-access.sh" "$ext" latest "$output"
    grep -Fxq -- '--output' "$work/args"
    grep -Fxq -- "$output" "$work/args"
    grep -Fxq -- '--snapshot' "$work/args"
    grep -Fxq -- 'latest' "$work/args"
done

# Unsupported formats are not exported by the access kit.
if "$work/repo/hangar-access.sh" iso latest "$work/no-image.iso" >/dev/null 2>&1; then
    echo "Retired image export command must not succeed" >&2; exit 1
fi
test ! -e "$work/no-image.iso"
echo "Standalone restic access, disk-format dispatch and old-kit migration passed"
