#!/usr/bin/env bash
# Verify the actual GRUB+Xorriso BIOS/UEFI ISO packaging tools in CI.
# This does not claim that a restored OS has booted successfully.
set -euo pipefail
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/tree/boot/grub" "$work/tree/live" "$work/root"
printf 'test root\n' > "$work/root/example.txt"
printf 'fake test kernel\n' > "$work/tree/live/vmlinuz"
printf 'fake test initrd\n' > "$work/tree/live/initrd.img"
printf 'set timeout=5\nmenuentry "Hangar test" { linux /live/vmlinuz boot=live }\n' > "$work/tree/boot/grub/grub.cfg"
mksquashfs "$work/root" "$work/tree/live/filesystem.squashfs" -noappend -comp xz -no-progress >/dev/null
grub-mkrescue -o "$work/boot.iso" -V HANGAR_LIVE -iso-level 3 "$work/tree" >/dev/null 2>&1
test -s "$work/boot.iso"
xorriso -indev "$work/boot.iso" -report_el_torito plain > "$work/report" 2>&1
grep -q 'El Torito' "$work/report"
grep -Eq 'EFI|UEFI' "$work/report"
grep -q 'BIOS' "$work/report"
xorriso -osirrox on -indev "$work/boot.iso" -extract /boot/grub/grub.cfg "$work/from-iso.cfg" >/dev/null 2>&1
cmp "$work/tree/boot/grub/grub.cfg" "$work/from-iso.cfg"
echo "GRUB BIOS+EFI ISO packaging and contents validated (not a live-system boot test)"
