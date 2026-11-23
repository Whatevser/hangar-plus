# Hangar

**Back up a Linux host from Cockpit. Browse yesterday's files, restore what matters, and recover a complete system without depending on Hangar itself.**

Hangar is a [Cockpit](https://cockpit-project.org/) interface over [restic](https://restic.net/) and systemd. It manages encrypted backup repositories, scheduled jobs, retention, container volumes, snapshot browsing, restores, and recovery exports. It does not invent a proprietary backup format or require a database.

> **Current scope:** Hangar manages the **Linux machine running Cockpit**. The bootable-disk exporter supports **x86-64 UEFI Linux systems**, not arbitrary operating systems. Exporting an image is **not a verified boot test**.

## Quick start

Requirements: **Cockpit 300+**, Linux with **systemd**, administrator access through Cockpit, and **restic 0.17+**. Hangar can offer to install restic through its dependency setup screen.

~~~sh
git clone https://github.com/Whatevser/hangar-plus.git
cd hangar-plus
sudo make install
sudo systemctl try-restart cockpit
~~~

Open **Cockpit → Hangar** and:

1. **Repositories:** Add a destination, or **Import existing…** to reconnect a previous local restic repository.
2. **Jobs:** Choose the files/directories or container volumes to protect, select the destination, schedule, and retention.
3. **Jobs → Run now:** Create a first snapshot. Scheduled runs continue through systemd timers.
4. **Logbook:** Choose a repository and a moment in time to browse, download, restore, or export it.

Hangar's UI follows Cockpit's light/dark setting. The dependency screen can provision **restic**, **rclone**, and **fuse3** where supported; specialist ISO/disk-export tooling is listed [below](#requirements-and-optional-tools).

## Screens

| Screen | What you can do |
| --- | --- |
| **Overview** | See the health of jobs, recent outcomes, unreadable-file warnings, destination/authentication problems, repository sizes, and actionable fixes. |
| **Jobs** | Create, edit, enable, disable, run, stop, and inspect scheduled backups. Configure source types, consistency, schedules, retention, and hooks. |
| **Repositories** | Manage local/remote restic destinations, import an existing local repository, test connectivity, initialize, unlock, check integrity, monitor size, and configure size safeguards. |
| **Logbook** | Browse snapshots on a timeline, inspect change badges, copy mounted paths, download files/ZIPs, restore selections, export a data ISO, or produce a bootable virtual disk. |
| **Settings** | Adjust Logbook mount behavior, failure reporting, repository-size refresh, dependency diagnostics, and GitHub-based Hangar updates. |

### Screenshots

![Overview showing backup health and actionable problems](screenshots/overview.png)

![Logbook timeline and file tree](screenshots/logbook.png)

![Job configuration and recent results](screenshots/jobs.png)

![Local and remote backup destinations](screenshots/repositories.png)

Additional examples: [repository setup](screenshots/repository-add.png), [password generator](screenshots/password-generator.png), [folder picker](screenshots/folder-picker.png), and [Settings](screenshots/settings.png).

## Repositories and destinations

All repositories use **restic's encrypted, deduplicated format**. The encryption happens before data reaches a remote destination.

Hangar supports these restic destination types directly:

| Type | Example |
| --- | --- |
| **Local path** | Internal disk, mounted USB disk, NAS mount |
| **SFTP** | SSH-accessible server |
| **REST** | restic REST server |
| **S3** | Amazon S3 and compatible object storage |
| **Backblaze B2** | Native B2 API |
| **Azure** | Azure Blob Storage |
| **GCS** | Google Cloud Storage |
| **rclone** | A configured rclone remote and path |

### rclone destinations

Use the built-in rclone wizard under **Repositories** to configure many additional services, including Google Drive, OneDrive, Dropbox, Box, pCloud, Mega, WebDAV, SMB, FTP, and others. You can also select an existing rclone remote.

Authentication depends on the provider:

- **Username/key credentials:** Supply fields in Hangar's form where the provider supports them.
- **Browser/OAuth sign-in:** For headless servers, Hangar displays an \`rclone authorize\` command to run on a computer with a browser. Paste the resulting token into Hangar.
- **Manual configuration:** Some providers, notably **Jottacloud**, require interactive \`rclone config\` outside the wizard; Hangar can then use the configured remote.

Google Drive's shared rclone client ID may be heavily rate-limited; a personal client ID is recommended for sustained use. Business OneDrive tenants can require their own app registration. Providers may expire tokens or impose quotas; Hangar attempts to identify expired authorization and offers a reconnection action.

Using a native restic destination when one is available avoids an extra rclone process. A second rclone \`crypt\` layer normally isn't necessary: restic already encrypts its repository.

### Recover an existing repository

**Repositories → Import existing…** adds an existing **local** restic repository *without reinitializing or copying it*. Point Hangar at the directory containing restic's \`config\` file and provide the **original password**. Hangar verifies that it can list snapshots before registering the repository; on failure it does not leave a new usable repository entry behind.

**Do not initialize an existing repository** to recover it. Import it instead.

### Repository size safeguards

Repositories can have a **size limit** and a **minimum snapshot floor**. After a backup, Hangar can inspect the repository's actual stored size and prune older snapshots iteratively when the configured guard allows it. Deduplication makes the reclaimed space unpredictable, so this is not an exact-size promise. Guard settings show the trade-offs rather than silently deleting history.

If **any local Hangar job targeting a repository has retention disabled**, the backup runner protects that repository against both its normal policy pruning and size-limit pruning. This is intentionally conservative.

Repository-size measurements can be slow for remote storage. Overview remembers the previous measurement and its timestamp; **Settings** controls when it should be refreshed, with an option to measure only on demand.

## Jobs, schedules, and consistency

A job selects a repository and one or more sources. Sources include:

- **Files and directories:** Paths on the Cockpit host, exclusions, exclusion files, one-filesystem behavior, and snapshot tags.
- **Container volumes:** Named **Podman** or **Docker** volumes. Hangar asks the runtime for their mountpoints, including rootless-user configurations where specified.

For container data, choose a consistency strategy:

| Mode | Behavior | Important caveat |
| --- | --- | --- |
| **Live copy** | Back up mounted files while containers run | Unsafe for databases receiving writes |
| **Pause** | Pause selected containers during copying | In-memory buffered writes may not reach disk |
| **Stop** | Stop containers, copy files, then restart | Consistent file-level snapshot, but causes downtime |
| **Dump command** | Execute a supplied database dump command and back up its output | You must write the dump into a volume that the job backs up |

Hangar warns about likely live-database risks. Container pause/stop cleanup belongs to the systemd-owned backup runner, not the browser session.

Jobs can use **hourly, daily, weekly, or custom systemd calendar schedules**. The generated timer uses \`Persistent=true\`, so missed runs can be picked up after the machine returns online. **Run now** starts the corresponding systemd unit; closing Cockpit doesn't stop the backup. The Jobs screen reads running state and journal progress again when reopened.

### Retention

The default is **Rolling**: **24 hourly, 30 daily, 52 weekly, 12 monthly** snapshots. Retention is grouped by **host and backed-up paths**, so unrelated systems and source trees are not thinned together.

Available presets include **Minimal**, **Rolling**, **Paranoid**, **Space saver**, **Last 30 days**, **Last 90 days**, **Last year**, and **Recent then thin**. A **Custom** policy supports counts, time windows, and protected tags.

Choose **Disable** to keep snapshots until you delete them manually. Retention is about *which snapshots remain*, not a guarantee that backups will use a fixed amount of disk space.

### Results and remediation

Hangar distinguishes a completed snapshot with unreadable files (**partial**) from a failed backup. restic exit code **3** means some source files could not be read but the snapshot may still have been written; Hangar lists the unreadable paths instead of treating the entire run as a total failure. Repository-not-found, lock, wrong-password, and expired-authorization errors have contextual recovery actions where possible.

Backup progress comes from restic's JSON messages, not a guessed timer. Job outcomes and operational logs are available through systemd/journald.

## Logbook: browse, download, restore

Choose a repository, then a snapshot on the timeline. The Logbook can use a **read-only restic FUSE mount** to expose that moment as a directory tree on the Cockpit host. File change badges compare adjacent snapshots. If a usable mount is unavailable, Hangar can fall back to browsing with \`restic ls\`.

- **Open a directory** to browse that snapshot's tree; **Copy path** copies the corresponding mounted host path when one exists.
- **Download** a selected file or a selected folder as a ZIP archive in your browser.
- **Restore…** selected files/folders to an **alternate location** by default. Optionally omit the selected items' original parent directories. Restoring to original paths is a separate, potentially destructive choice.
- **Create ISO…** exports a **decrypted, non-bootable data ISO** of the snapshot. An ISO is for file recovery and does not faithfully reproduce all Unix filesystem metadata.
- **Create disk…** builds a virtual boot disk from a **complete Linux-system snapshot**; see the next section.

The mount location, idle-unmount interval, and **Allow local access** setting live in **Settings**. Allow local access exposes mounts to local Linux users subject to saved Unix permissions; consider the confidentiality implications before enabling it.

**Connection behavior matters:** Logbook browsing, a manual restore, data ISO creation, repository checking, and pruning are **not all independent of the Cockpit connection**. Avoid closing the tab during those manual operations. Normal background backups and bootable-disk exports use independent systemd jobs.

## Bootable virtual disks: RAW by default

**Logbook → Create disk…** produces a **decrypted virtual disk** from a selected **full Linux root snapshot**. It **does not create or boot a VM**. The output filename determines the format:

| Extension | Format | Recommended use |
| --- | --- | --- |
| **\`.raw\`** (default) or \`.img\` | Sparse RAW disk | **Cockpit Virtual Machines, libvirt, QEMU/KVM on Linux** |
| \`.vhdx\` | VHDX | Systems needing the VHDX format, such as Hyper-V |
| \`.vhd\` | Legacy VHD | Legacy consumers; subject to a smaller disk-size limit |

### What Hangar actually builds

1. Allocate a **private, sparse RAW disk** sized from restic's logical restore size plus headroom (minimum 16 GiB).
2. Partition it as **GPT** with a **512 MiB FAT32 EFI System Partition** and an **ext4 root partition**.
3. Attach it using a verified loop device, format the partitions, and run **restic restore directly into ext4**, preserving supported metadata.
4. Check the restored system for a matching **kernel, initramfs, and modules**; update **the image's** root UUID/fstab and GRUB configuration; install a removable **x86-64 UEFI GRUB** loader into **the image's** EFI partition.
5. Unmount and detach. For **RAW**, publish that same sparse disk directly. For **VHDX/VHD only**, run \`qemu-img convert\` to create the requested output.

**RAW avoids the extra conversion and extra populated image copy.** A RAW disk's *virtual capacity* can be much larger than its actual allocated blocks: compare \`ls -lh\` (logical size) with \`du -h\` (space used). Use sparse-aware copy tools when moving it.

### Progress, cancellation, and reconnection

Exports run as **independent transient systemd services**, coordinated by \`hangar-vhd-job\`. Logbook shows live **restic restore percentage/bytes**, preparation/bootloader stages, and **conversion percentage** when converting to VHDX/VHD. It records errors and final status in private files under \`/var/lib/hangar/vhd/\`.

While active, **Create disk…** changes to **Abort disk**. Cancellation requests stop the worker, terminate the current child command, and attempt to unmount/detach temporary devices safely. A Cockpit WebSocket disconnect or browser close **does not terminate the export**; open Logbook again to recover the saved status. Only **one disk export per host** runs at once.

Output files are not silently overwritten. The disk contains plaintext data and credentials from the restored system; protect it like a copy of the source machine.

### What these images can—and cannot—boot

The exporter targets **x86-64 UEFI, systemd-based Linux installations with an unencrypted ext4 root** and a complete snapshot including \`/etc\`, \`/boot\`, kernel modules, and initramfs.

It **does not** recreate encrypted-root/LUKS, Btrfs/ZFS/LVM layouts, independent \`/boot\` partitions, or a BIOS/legacy bootloader. **Secure Boot is unsupported** by the generated unsigned EFI bootloader. It does not inspect or repair a VM's firmware settings.

For **Cockpit Virtual Machines**, select **UEFI/OVMF firmware with Secure Boot disabled** and attach a \`.raw\` disk with the QEMU/libvirt **raw** driver. Make sure the VM's QEMU process can access the file *and every parent directory*. Firmware, virtual disk controller, and initramfs driver differences may still prevent boot.

**An export reporting “completed” means files, partitions and the EFI bootloader were assembled—not that the machine booted successfully.** No automatic VM boot test is performed.

## Recover without Hangar: Access kit

For a **local** repository, **Repositories → Access kit** can place these files beside the restic repository:

| File | Purpose |
| --- | --- |
| \`hangar-access.key\` | Copy of the repository password |
| \`hangar-access.sh\` | Standalone restic/ISO/disk recovery commands |
| \`hangar-vhd.py\` | Standalone bootable disk builder (supports RAW and VHDX/VHD despite the historical filename) |

Re-running **Access kit** can update recognized older generated scripts. It refuses to overwrite an unknown customized script, a symlinked builder, or a mismatched key.

After connecting that drive to another Linux host:

~~~sh
cd /path/to/restic-repository
sudo ./hangar-access.sh snapshots
sudo ./hangar-access.sh restore latest --target /path/to/recovery
sudo ./hangar-access.sh iso latest /absolute/path/snapshot.iso
sudo ./hangar-access.sh raw latest /absolute/path/system.raw
# Alternatives: vhdx .../system.vhdx or vhd .../system.vhd
~~~

The script uses standard restic commands for listing/restoring; ISO and disk exports need their corresponding tools installed on the recovery host.

**Critical security trade-off:** This is opt-in. Keeping \`hangar-access.key\` **next to the encrypted repository** means someone who copies the drive can decrypt the backups. Keep independent, protected copies of repository credentials if you choose *not* to use the access kit.

## Settings, updates, and troubleshooting

Settings includes:

- Snapshot mount directory (default \`/run/hangar/mnt\`), idle unmount, and local-access permissions.
- Repository-size measurement age, including on-demand-only refresh.
- Failed-backup reporting and dependency diagnostics with a copyable bug-report summary.
- **Check GitHub**, **Install update**, and optional **Automatic updates**.

**Self-update** follows [\`Whatevser/hangar-plus\` \`main\`](https://github.com/Whatevser/hangar-plus). The updater installs newer Cockpit files and privileged helper executables, and detects missing helpers even when the recorded commit is already current. It preserves \`/etc/hangar\`, repository definitions and passwords. Reload Cockpit after a manual update.

Automatic updates use \`hangar-auto-update.timer\` **twice daily**; they are **off by default** until explicitly enabled.

Useful diagnostics on the Linux host:

~~~sh
# Scheduled job and recent log (replace JOB_ID):
systemctl status 'hangar-backup@JOB_ID.service'
journalctl -u 'hangar-backup@JOB_ID.service' -n 100 --no-pager

# Active/durable disk exports:
sudo python3 /usr/libexec/hangar/hangar-vhd-job status

# Confirm a RAW image is really RAW:
file /absolute/path/system.raw
~~~

If an export or mount fails, inspect the actionable message and the service journal. FUSE availability, missing GRUB utilities, file permissions, and insufficient temporary storage are distinct problems; don't treat every boot failure as a corrupt restic snapshot.

### Files and system services

Hangar has **no dedicated always-running application daemon or database**. Existing Linux services and files are its source of truth:

| Location | Contents |
| --- | --- |
| \`/etc/hangar/config.json\` | Global settings |
| \`/etc/hangar/repos/<id>.json\` | Repository definitions (not passwords) |
| \`/etc/hangar/repos/<id>.key\` | Root-protected repository passwords |
| \`/etc/hangar/jobs/<id>.json\` | Job definitions |
| \`/etc/systemd/system/hangar-backup@*.{service,timer}\` | Scheduled job units |
| \`/var/lib/hangar/state/\` | Persisted backup-run summaries |
| \`/var/lib/hangar/vhd/\` | Background bootable disk export state |
| \`/run/hangar/mnt/\` | Default transient snapshot mounts |
| \`/usr/libexec/hangar/\` | Privileged runner, updater, portable exporter, and disk-builder helpers |
| journald | Service logs and historical details (subject to journal retention) |

You can work with restic repositories independently of Hangar.

### Updating and uninstalling from a checkout

~~~sh
# Reinstall/update from a checked-out source tree:
git pull
sudo make install
sudo systemctl try-restart cockpit

# Uninstall Cockpit plugin, helpers, and cache:
sudo make uninstall
~~~

**Uninstall behavior:** The Makefile deliberately preserves \`/etc/hangar\`, including repository passwords and job configuration, but **removes \`/usr/libexec/hangar\`**. Existing systemd backup timer/unit definitions may remain, but their backup runs **will fail without the removed \`hangar-run\` executable**. Disable/remove managed timers or keep the runner installed if you intend to continue running backups without the UI. Uninstalling does **not** delete restic repositories.

## Requirements and optional tools

| Component | Required for | Provisioning |
| --- | --- | --- |
| **Cockpit 300+**, Linux, systemd, administrator permissions | Hangar itself | Install on the host |
| **restic 0.17+** | Backup, browse, restore, repository management | Hangar dependency setup can install it |
| **rclone** | rclone-backed destinations | Hangar dependency setup can install it |
| **fuse3** | Snapshot FUSE browsing | Hangar dependency setup can install it; \`restic ls\` is a fallback |
| **xorriso** | Non-bootable data ISO export | Install separately if unavailable |
| **sfdisk, losetup, mount, umount, blkid, mkfs.vfat, mkfs.ext4** | Bootable disk creation | Host disk/FS tools; check before exporting |
| **grub-install** plus x86-64 EFI modules | Bootable UEFI disks | Install the host's GRUB EFI tooling |
| **qemu-img** (\`qemu-utils\`) | **Only VHDX/VHD** conversion | **Not needed for RAW export** |
| **Podman or Docker** | Corresponding container-volume jobs | Runtime must already manage those volumes |

On RHEL-family distributions, restic may require EPEL; Hangar can offer a static-binary fallback where appropriate. PackageKit and available package sources vary by distro; Hangar cannot guarantee every optional recovery utility will be installed automatically.

## Security and limitations

- **Encryption:** restic encrypts repositories. Root can read the password key files in \`/etc/hangar/repos/\`; protect the host and backups accordingly.
- **Systemd credentials:** Backup jobs provide repository passwords using \`LoadCredential=\` rather than exposing passwords in process arguments.
- **Decrypted exports:** Downloaded files, data ISOs, RAW/VHDX/VHD images, and access kits can reveal private contents. They are **not encrypted restic repositories**.
- **Container consistency:** Pausing a database process is not equivalent to obtaining an application-consistent backup. Use clean shutdown or verified dumps.
- **No cluster dashboard:** Hangar manages one Cockpit host; restic snapshots record their host/path identity and multiple hosts can use supported shared repositories, but Hangar is not a multi-host orchestration system.
- **Not every manual operation is detached:** Browser-connected tasks may be interrupted by a lost Cockpit session. Systemd backup jobs and bootable disk exports are the explicit durable exceptions.
- **No boot guarantee:** A bootable disk export is best-effort reconstruction of a supported Linux layout, not cloning every partition, service, hardware driver, or firmware configuration.
- **History is finite:** journald rotation can remove older run logs; persistently tracked summaries and the restic repository are separate from journal history.

## Development and testing

~~~sh
npm run test:unit           # JS unit tests, no coverage instrumentation
make test                   # JS unit tests with coverage floors
make coverage               # Coverage report and coverage/lcov.info
npm run test:integration    # Node integration tests (real restic where available)
npm run test:smoke          # Structural invariants
npm install
npm run test:e2e            # Playwright + stubbed Cockpit bridge
npm run test:ui             # Playwright against a real Cockpit session
python3 tests/integration/vhd_test.py
python3 tests/integration/vhd_job_test.py
python3 tests/integration/updater_helper_repair.py
~~~

Other Linux integration scripts include \`tests/integration/portable-live.sh\` for real restic/standalone access-kit behavior. Some integration scenarios need installed tools, root permissions, or supported container runtimes and are not interchangeable with browser stubs.

**Coverage caveat:** Node coverage measures the JavaScript source, **not** the privileged Python runner, native restic, Linux mount operations, or whether a generated image boots. Browser tests with a stubbed Cockpit bridge do not prove live-host integration. For \`test:ui\`, provide \`COCKPIT_URL\`, \`COCKPIT_USER\`, and \`COCKPIT_PASS\`, or a protected JSON file via \`COCKPIT_CREDENTIALS_FILE\` outside this repository.

## License

See [LICENSE](LICENSE).
