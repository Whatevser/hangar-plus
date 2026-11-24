# Hangar

A [Cockpit](https://cockpit-project.org/) interface for [restic](https://restic.net/) backups on one Linux host. Manage encrypted local/cloud repositories, systemd-scheduled jobs, retention, container volumes, snapshot browsing, restores and bootable virtual disk exports. No separate daemon or database.

## Install

**Requirements:** Linux with systemd, **Cockpit 300+**, administrator access, and **restic 0.17.0+**. Disk exports require **x86-64 Linux**.

### Ubuntu / Linux Mint / Debian

Install the dependencies for **all features**, including optional remote storage, FUSE browsing, virtual disk conversion and RAW repair:

~~~sh
sudo apt update
sudo apt install -y cockpit python3 git make restic rclone fuse3 packagekit \
  fdisk util-linux mount dosfstools e2fsprogs grub-common grub-efi-amd64-bin \
  qemu-utils psmisc
~~~

You do **not** need every package for ordinary backups: `rclone` is for rclone-backed storage, `fuse3` enables mounted snapshot browsing (otherwise Hangar uses `restic ls`), `qemu-utils` converts VHD/VHDX/QCOW2/VDI/VMDK (not RAW/IMG), and the disk/GRUB packages are for bootable exports. `psmisc` supplies `fuser` for RAW repair. `packagekit` supports Hangar's in-app prerequisite installer. Podman/Docker are only needed for container-volume jobs.

**Restic version caveat:** Some distribution repositories are older than Hangar's requirement. For example, Ubuntu 24.04 supplies restic **0.16.4**, which lacks the exit codes Hangar needs to distinguish missing and locked repositories. **Check after installing:**

~~~sh
restic version
~~~

If the version is **below 0.17.0**, install the current official, signature-verified release **alongside** the distribution package, not over the package-managed binary:

~~~sh
sudo restic self-update --output /usr/local/bin/restic
hash -r  # clear an earlier shell lookup of /usr/bin/restic
command -v restic
restic version
~~~

`/usr/local/bin` normally takes precedence over `/usr/bin`; `command -v restic` should show `/usr/local/bin/restic`. The systemd services must also resolve the newer binary. An ordinary `apt upgrade` then won't overwrite the independent copy. Restic's [installation guide](https://restic.readthedocs.io/en/stable/020_installation.html) documents its verified self-updater and `--output` option. On RHEL-family systems, restic may require **EPEL**; other distributions use their own package managers.

### Install Hangar

~~~sh
git clone https://github.com/Whatevser/hangar-plus.git
cd hangar-plus
sudo make install
sudo systemctl enable --now cockpit.socket
~~~

Open **Cockpit → Hangar**. Create or import a repository, add a job, then choose **Run now** for the first snapshot. For updates, use **Settings → Check GitHub → Install update**, or `git pull && sudo make install` from the checkout.

## What Hangar does

| Screen | Functions |
| --- | --- |
| **Overview** | Backup health, recent results, repository size, warnings and repairs |
| **Repositories** | Local, SFTP, REST, S3, B2, Azure, GCS and rclone destinations; import, test, check, unlock and size safeguards |
| **Jobs** | Files/directories, exclusions, Podman/Docker volumes, hooks, schedules, retention and run controls |
| **Logbook** | Snapshot timeline, change comparison, browse, download, restore and Create disk |
| **Settings** | Mount path and permissions, Remount, failure notices, diagnostics and updates |

![Logbook: snapshot timeline](screenshots/logbook.png)

**Repositories:** Restic encrypts and deduplicates data before upload. Native destinations include local, SFTP, REST, S3, B2, Azure and GCS. The rclone wizard supports Google Drive, Dropbox, OneDrive, Box, pCloud, Yandex Disk, WebDAV, SFTP, FTP, SMB, S3, Backblaze B2, OpenStack Swift, Koofr and MEGA; OAuth providers may need `rclone authorize` on a browser-equipped computer.

| Setup | Provider | How |
| --- | --- | --- |
| **Manual** | Jottacloud | Use interactive `rclone config` first, then select the remote in Hangar |

**Import existing…** reconnects a local restic repository using its original password; **never initialize an existing repository** just to reconnect it.

**Jobs:** Hourly, daily, weekly and custom systemd timers survive Cockpit disconnections; missed runs can be caught up. Retention presets and custom policies operate on snapshots, with repository size limits and protected snapshots. Container sources can be copied live, paused or stopped; active databases may need consistent dumps instead. Backup results distinguish unreadable files (partial snapshot) from outright failures.

**Logbook:** Uses a read-only restic FUSE mount where available, otherwise `restic ls`. Restore defaults to a separate directory; recent destinations and the "without original parent folders" preference are remembered in the browser. Settings → **Remount** applies a changed snapshot mount path to the selected repository immediately. Allowing local users to browse mounts may expose recovered files.

## Bootable virtual disks

**Logbook → Create disk** asks for an absolute filename **without** its extension, then offers:

| Format | Output | Dependency |
| --- | --- | --- |
| **RAW / IMG** | Sparse, directly usable disk; RAW is the default | Disk and GRUB tools |
| **VHD / VHDX** | Legacy VHD / Hyper-V disk | `qemu-img` |
| **QCOW2** | QEMU/KVM disk | `qemu-img` |
| **VDI** | VirtualBox disk | `qemu-img` |
| **VMDK** | VMware disk | `qemu-img` |

All formats start from **the same RAW disk builder**: create GPT, a 512 MiB FAT32 EFI partition and an ext4 root partition, restore the full restic snapshot, then embed its boot locator in standalone UEFI GRUB. RAW/IMG are published directly; other formats are converted with `qemu-img`. Exports run as independent systemd jobs with progress, cancellation and reconnectable status. Existing output files are not overwritten.

**Limits:** Requires a complete **x86-64 UEFI Linux** snapshot with kernel, initramfs and modules. This is **not a clone of the original partition layout**: encrypted roots, LUKS/LVM, Btrfs/ZFS, separate boot layouts and legacy BIOS are not reconstructed. The EFI loader is unsigned: **disable Secure Boot** in the guest. Hangar does **not** launch a VM or verify that the image boots. VM disk permissions and guest drivers may still need attention.

### Repair an older RAW/IMG disk stuck at `grub>`

With the VM **fully powered off** (and Secure Boot disabled):

~~~sh
sudo python3 /usr/share/cockpit/hangar/libexec/hangar-vhd \
  --repair-raw /absolute/path/image.raw
~~~

Repair checks the image's EFI/root partitions, avoids in-use disks, and rebuilds the embedded GRUB config without re-restoring the snapshot. It keeps a backup of the previous EFI loader. It does **not** repair a missing kernel/initramfs or support VHD/VHDX conversion in place.

## Offline recovery: Access kit

For a **local** repository, **Repositories → Access kit** places three files beside the backup: `hangar-access.sh` (independent launcher), `hangar-access.key` (repository password) and `hangar-vhd.py` (full disk builder). On another compatible Linux host, install the required tools, then:

~~~sh
cd /path/to/restic-repository
sudo ./hangar-access.sh snapshots
sudo ./hangar-access.sh restore latest --target /path/to/recovery
sudo ./hangar-access.sh raw latest /absolute/path/system.raw
# Also: img, vhd, vhdx, qcow2, vdi, vmdk
~~~

No Hangar or Cockpit installation is needed on the recovery host. **Re-run Access kit** after updating Hangar to refresh older generated scripts and the builder; customized scripts and mismatched keys are never silently replaced.

**Security warning:** Access-kit keys, downloaded/restored files and disk images contain sensitive plaintext. Keeping `hangar-access.key` alongside its encrypted repository means someone with the drive can decrypt that backup.

## Maintenance

- **Settings** can update from GitHub `main` and optionally enable twice-daily automatic update checks. Configuration under `/etc/hangar` remains in place.
- Jobs are systemd units; logs are available in journald: `journalctl -u 'hangar-backup@JOB_ID.service' -n 100 --no-pager`.
- Disk export status: `sudo python3 /usr/libexec/hangar/hangar-vhd-job status`.
- `sudo make uninstall` removes the plugin/helpers, **not repositories or `/etc/hangar`**. Disable old Hangar timers first; without the removed runner, their jobs will fail.
- Hangar manages **one Cockpit host**, not a cluster. Some manual browser operations can be interrupted by disconnects; systemd backups and disk exports continue.
- Source tests: `npm install`, `make test` (JavaScript), `npm run test:smoke`, `python3 tests/integration/vhd_test.py`. Real disk/boot behavior requires host-side testing.

[Changelog](CHANGELOG.md) · [More screenshots](screenshots/) · [License](LICENSE)
