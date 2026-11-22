# Hangar

A Cockpit plugin for creating and managing backups.

## What it does

**Scheduled backups.** Jobs run from systemd timers with `Persistent=true`, so a
run missed while the machine was asleep fires when it wakes.

**Automatic thinning.** The **Rolling** retention preset keeps 24 hourly, 30
daily, 52 weekly and 12 monthly snapshots, grouped per host and path. Old
snapshots age out automatically.

Choose **Disable** under job retention to keep every snapshot for manual deletion
in the Logbook. While any local job using that repository has retention disabled,
Hangar skips both policy pruning and size-limit pruning for that repository.

**The Logbook.** Scroll back through every moment your data was captured and
browse the filesystem exactly as it was. This is a real
[FUSE](https://en.wikipedia.org/wiki/Filesystem_in_Userspace) mount of the
snapshot, not a reconstruction — so it is an ordinary directory tree, and
restoring a file is copying it. Change badges show what was added, modified or
removed between adjacent snapshots.

When a snapshot is mounted, **Copy path** copies the current folder's absolute
path on the Cockpit host. Enable **Allow local access** in **Settings** to let
local accounts browse new read-only mounts under the saved Unix permissions.

Select one file or folder and click **Download** to save the file or a folder
ZIP in your browser. In the restore dialog, **Restore without original parent
folders** puts selected items directly in the destination and preserves the
structure inside selected folders.


**Import existing repository** (Repositories → Import existing…) attaches an
existing local restic repository folder without copying its data or running
`restic init`. Enter the directory that contains restic's `config` file and
the original password. Hangar must successfully list its snapshots **before**
it saves a new repository definition. If verification fails, the temporary
stored password is removed and the repository stays unregistered. This is
the correct way to use an intact backup after reinstalling the system.

**Create ISO** in the Logbook writes a **decrypted, non-bootable data ISO**
for the selected snapshot. It requires `xorriso`, plus free space for the
temporary restored files and the finished ISO. It is not a clone of the
encrypted restic repository, and it cannot preserve all Linux metadata.


**Experimental Live ISO (test)** is separate from the existing data ISO.
It restores a complete **x86_64 Debian/Ubuntu/Linux Mint system snapshot** into
temporary private storage, builds `live/filesystem.squashfs`, generates a
**fresh live-boot initramfs from the currently running machine's exact kernel**,
and uses GRUB to construct a bootable ISO for BIOS/UEFI. Its default menu
option opens a **non-networked inspection shell** (`init=/bin/bash`) without
starting the snapshot's services. A second experimental entry starts systemd
in multi-user mode. The root uses a temporary RAM overlay; changes to this
live session are discarded. It **does not restore or overwrite any disks**.

A complete snapshot of the same OS version must include the matching kernel
modules and systemd; a partial `/home` backup will be refused. The builder
writes an empty `/etc/fstab` and `/etc/crypttab` **in its temporary restored
copy only** and disables Hangar's own timers there to avoid auto-mounting the
original system's partitions. Your original snapshot and installed boot
configuration are never touched.

**Do the first build on a disposable cloned/test Linux environment, not a
production install:** Debian specifically warns that `live-boot-initramfs-tools`
is intended for live images, not for installation on a regular system.
The kernel and modules used by that build environment must match those in
the snapshot.

The machine building the image must have `restic`, `mkinitramfs`,
`lsinitramfs`, `live-boot` with `live-boot-initramfs-tools`,
`squashfs-tools`, `xorriso`, `grub-mkrescue`, `grub-pc-bin`,
`grub-efi-amd64-bin` and `mtools` available. Hangar does **not**
automatically install these optional test dependencies. Secure Boot is not
supported by the unsigned experimental image.

**Test only in an isolated virtual machine with no real disks or host
filesystems attached**, initially using the default inspection shell. Full
system boot remains unproven until you test your particular snapshot. Disk
access and startup services in the full-boot entry are not generally safe to
assume harmless on physical hardware. The ISO includes ALL restored files,
including **unencrypted credentials, SSH keys and passwords**, and may require
considerable scratch disk space. Do not distribute it.

The optional local access kit also provides:
```sh
sudo ./hangar-access.sh live-iso latest /absolute/path/test-live.iso
```
This command uses the `hangar-live-iso.py` stored with the access kit; it
can run after Hangar is removed, provided the live-boot build dependencies
are installed. Trigger **Repositories → Access kit** again to upgrade a
previously generated kit to this format without changing its restic password.

The original restic password is stored separately at
`/etc/hangar/repos/<id>.key` and is NOT embedded in the encrypted
repository. To use the backup independently of Hangar, local repositories
offer an opt-in **Access kit** action that places `hangar-access.key` and
`hangar-access.sh` beside the repository. This works retroactively; clicking
Access kit again upgrades older generated scripts without overwriting the
password. Unrecognized custom scripts or mismatched keys are never
overwritten.

The script needs only `restic` to browse or restore snapshots, or both
`restic` and `xorriso` to create an ISO. After mounting your backup drive
on **any Linux host**, run in the repository directory:

```sh
sudo ./hangar-access.sh snapshots
sudo ./hangar-access.sh iso latest /absolute/path/backup.iso
# Or replace latest with a particular restic snapshot ID.
```

That ISO command works **without Hangar and without Cockpit**. It uses the
local repository and password file directly, never alters existing
snapshots, and refuses to overwrite an ISO. It needs free space for the
temporary decrypted files and the ISO.

**Security trade-off:** Putting the key beside an encrypted repository means
anyone who copies both can decrypt every snapshot. The access kit is always
optional and only applies to local repositories.


**Anywhere for a destination.** Local disk, USB, SFTP, a REST server, Amazon S3,
Backblaze B2, Azure, Google Cloud Storage, or any
[rclone](https://rclone.org/overview/) remote — which covers most of the rest.

**Turnkey.** Hangar installs what it needs. It never tells you to go and run a
package manager.

**Cockpit appearance.** Hangar uses Cockpit's light/dark preference (or the
system preference when Cockpit is set to automatic) rather than maintaining its
own themes. In Cockpit, the content area uses the same rounded, inset page
surface as Binup; smaller windows use the full available width.

---

## What it looks like

![The Overview screen: three jobs with their last result, a banner about an expired cloud sign-in, and repository sizes](screenshots/overview.png)

*Overview — one screen that says whether your backups are fine. A job that
succeeded, one that finished with unreadable files, and one that failed because
the cloud destination's sign-in expired, with the fix next to it.*

![The Logbook: a snapshot's file tree beside a timeline of moments, with change badges on the files that differ from the previous snapshot](screenshots/logbook.png)

*The Logbook — scroll back through every captured moment and browse the
filesystem as it was. Badges mark what changed since the snapshot before it.*

![The Jobs screen: three jobs with their schedule, retention policy and last result](screenshots/jobs.png)

*Jobs — what is backed up, where it goes, how often, and how long it is kept.*

![The Repositories screen: a local folder and a Backblaze B2 bucket, each with its size and snapshot count](screenshots/repositories.png)

*Repositories — every destination with its real size and snapshot count.*

![The repository password dialog with a generated six-word passphrase](screenshots/password-generator.png)

*A repository password cannot be recovered, so the dialog helps you make a
strong one you can still type at a rescue console — and will not let you past it
without noticing you must store it.*

![The Add repository dialog, showing the destination kinds hangar can talk to](screenshots/repository-add.png)

*Adding a destination — a local folder, an SFTP server, or one of sixteen cloud
providers, in one form.*

![The folder picker, browsing the filesystem to choose a path](screenshots/folder-picker.png)

*Every path in hangar can be browsed instead of typed, as root, without leaving
the page.*

---

## Cloud destinations

Hangar speaks four object stores natively — **Amazon S3** (and S3-compatible
providers), **Backblaze B2**, **Azure Blob Storage** and **Google Cloud
Storage** — plus local disks, USB drives, SFTP and a
[restic REST server](https://github.com/restic/rest-server).

Everything else goes through [rclone](https://rclone.org/overview/), which adds
roughly forty more: **Google Drive, Dropbox, OneDrive, Box, pCloud, Mega, Proton
Drive, iCloud Drive**, Yandex Disk, Koofr, Jottacloud, Seafile, and protocols
including **WebDAV, SMB/CIFS, FTP and HDFS**.

Two things worth knowing before you choose:

**Prefer the native backend where one exists.** If you are on S3, B2, Azure or
GCS, use Hangar's own repository kind rather than routing through rclone — one
less process in the path, one less thing to fail.

**Do not add rclone's `crypt` layer.** restic already encrypts everything
client-side before it leaves the machine. Layering `crypt` underneath buys
nothing and costs CPU; your provider holds encrypted restic packs either way.

### Adding a cloud destination

Hangar can create the rclone remote for you — **Repositories → Add a cloud
destination** — so `rclone config` is not a prerequisite. How much it can do
depends on how the provider authenticates.

| Kind | Providers | What you do |
|---|---|---|
| **Credentials** | WebDAV, SFTP, FTP, SMB, S3, B2, Swift, Koofr, Mega | Fill in the form. Nothing to run elsewhere. |
| **Sign-in** | Google Drive, Dropbox, OneDrive, Box, pCloud, Yandex | Run one command on **your own computer**, paste the result back. |
| **Manual** | Jottacloud | Hangar cannot automate it — it shows you what to run. |

### Why sign-in needs a command on your own computer

`rclone authorize` starts a local web server and asks the provider to redirect
your browser to `127.0.0.1` when you approve. Run it on the server and that
redirect points at the *server's* loopback address, which your laptop's browser
cannot reach.

So Hangar shows you the exact command, you run it where your browser is, and you
paste the token back. This is rclone's own documented headless procedure, not a
workaround Hangar invented.

### Per-provider limits

These are properties of the providers, not of Hangar, and Hangar states each one
at the point where you choose:

| Provider | Limit |
|---|---|
| **Google Drive** | rclone's built-in client ID is shared by every rclone user and is **heavily rate-limited**. For anything beyond a trial, register your own in the Google Cloud console — backups will be far faster. This is the only one Hangar flags as a warning rather than a note. |
| **OneDrive** | A **OneDrive for Business** tenant may refuse rclone's built-in client ID outright. Register an app in Entra ID. |
| **Box** | The refresh token **expires after 60 days of inactivity**. A repository that is never written to will eventually need re-authorising. |
| **pCloud** | Accounts live in one of two regions. If the remote lists nothing after you authorise, the account is in the other one. |
| **Dropbox, Yandex** | Shared-key rate limits and per-application quotas. Your own app registration avoids them; the built-in one is usually fine for modest backups. |
| **Jottacloud** | Works as a destination, but **Hangar cannot create the remote.** rclone has no `authorize` flow for it — verified, not assumed: `rclone authorize jottacloud` answers *"not supported by this backend"*. Generate a personal login token in Jottacloud's web interface, run **interactive** `rclone config` once, and Hangar will pick the remote up. Note that the non-interactive `rclone config create <name> jottacloud` **appears to succeed but leaves a remote with no token** — it will show up in Hangar's list and fail at backup time. Use interactive `rclone config`. |


## Requirements

- Cockpit 300 or newer
- systemd (any host running Cockpit has it)
- `restic` 0.17.0 or newer — Hangar installs it for you

Optional, installed on demand for the features that need them:

| Package | Needed for |
|---|---|
| `fuse3` | Browsing snapshots in the Logbook |
| `rclone` | Off-site destinations rclone reaches and restic does not |

### A note for RHEL, CentOS, Rocky and Alma

`restic` is not in the base repositories on these distributions — it lives in
[EPEL](https://docs.fedoraproject.org/en-US/epel/). If EPEL is enabled, Hangar
installs restic through PackageKit like anywhere else. If it is not, Hangar
offers the official static binary instead, showing you the release URL and its
SHA256 and asking before it downloads anything.

Debian, Ubuntu, Fedora, openSUSE and Arch all package restic directly, so
installation there is a single click.

---

## Installing

```sh
git clone https://github.com/Whatevser/hangar-plus.git
cd hangar-plus
sudo make install
sudo systemctl try-restart cockpit
```

Then open Cockpit and choose **Hangar** in the sidebar.

**Self-update:** Settings → Hangar updates checks the latest commit on
[Whatevser/hangar-plus](https://github.com/Whatevser/hangar-plus)'s `main`
branch. **Check GitHub** previews whether a newer commit exists; **Install
update** applies it without replacing `/etc/hangar` or stored repository
passwords. The **Automatic updates** switch enables a systemd timer
(`hangar-auto-update.timer`) which checks and installs twice per day,
including missed runs after boot. It is **off by default** until enabled.
The updater replaces the installed Cockpit files and helper scripts but does
not run any recovery or VM operations. Reload Cockpit after a manual update.

To remove it:

```sh
sudo make uninstall
```

Your configuration in `/etc/hangar` is deliberately left in place. Delete it
yourself if you want it gone — and note that removing Hangar does **not** stop
your backups, which is by design (see below).

---

## How it is built

Hangar has no daemon and no database. The system is the state store:

| State | Lives in |
|---|---|
| Schedule | systemd timers and units |
| Backup data and history | the restic repository |
| Job, repository and retention config | `/etc/hangar/**.json` |
| Run history and logs | journald, per unit |
| Secrets | `/etc/hangar/repos/<id>.key`, mode 0600 root:root |

The practical consequence: **uninstall Hangar and your backups keep running.**
Everything Hangar does is reproducible by hand with `systemctl`, `restic` and
`journalctl`, and nothing it manages is locked inside a format only it can read.
It is a view and an editor over system state, not an application that owns it.

The trade-off, stated honestly: Hangar cannot show you anything systemd and
restic cannot tell it. There are no cross-run analytics beyond what journald
retains.

### Layout

```
/etc/hangar/config.json          global settings
/etc/hangar/repos/<id>.json      repository definition (never secrets)
/etc/hangar/repos/<id>.key       repository password, 0600 root:root
/etc/hangar/jobs/<id>.json       job definition
/var/lib/hangar/state/<id>.json  last run record, survives reboot
/run/hangar/mnt/<repo>           transient Logbook mount
/usr/libexec/hangar/hangar-run   privileged backup runner
```

---

## Why restic

Hangar drives restic entirely through its `--json` output — progress bars come
from real `percent_done` messages, not from parsing human-readable text — and
restic's exit codes are specific enough to turn a failure into a *fix*:

| Exit | Meaning | What Hangar offers |
|---|---|---|
| 3 | Some files could not be read | Lists them. **The snapshot still exists** — this is not a failure |
| 10 | Repository does not exist | Initialise it |
| 11 | Repository is locked | Unlock it |
| 12 | Wrong password | Re-prompt |

That exit-3 row matters more than it looks. A backup where three unreadable
files turn the whole run red teaches you to ignore red. Hangar records it as
*partial*, tells you which files, and moves on.

Borg was the main alternative and was rejected: its repository is single-writer
under an exclusive lock, so a scheduled run and a manual one collide; remotes
are SSH-only with borg required at the far end; and borg 2.0 is a breaking
repository-format change still in beta.

---

## Security

- Repository passwords are passed to systemd units via `LoadCredential=`, not
  through the environment and not on the command line.
- Backend credentials are exported as environment variables, never as argv, so
  they never appear in `ps` output.
- Repository ids are validated to `[a-z0-9-]` before becoming filenames or
  systemd unit names, so path traversal is rejected at the boundary.
- restic repositories are always encrypted; there is no unencrypted mode to
  misconfigure.

Anyone with root can read the repository password. That is an accepted
trade-off — root can already read everything being backed up — and the secret
handling is isolated in one module so TPM-bound storage can replace it later.

---

## Testing

```sh
npm install          # only for the Playwright-based UI tests
make test            # unit tests with a coverage report and its floors
npm run test:unit    # the same tests, no coverage, for a fast inner loop
make coverage        # writes COVERAGE.html and coverage/lcov.info
npm run test:smoke   # structural checks on the shipped plugin
npm run test:integration   # real restic against a temp repository
npm run test:e2e     # Playwright, against a stubbed cockpit bridge
npm run test:ui      # Playwright, inside a real Cockpit session
```

### Coverage

`make test` measures line, branch and function coverage over `js/` and fails if
it drops below the floors in the Makefile — floors set a shade under what the
suite achieves today, so code that arrives untested turns the run red instead of
quietly moving the number down.

`make coverage` writes two files. `coverage/lcov.info` is the machine copy for
editors and is not committed. **`COVERAGE.html`** is the human one that is: one
row per source file, sortable by any column, opening worst-first. It is HTML
rather than Markdown because a Markdown table cannot sort, which means GitHub
shows it as source — open it from a checkout. It records percentages only; line
numbers would make it churn on every insertion above them, and a report that
changes when the testing did not is a report people stop reading.

The figure covers the browser sources and nothing else. `libexec/hangar-run` is
about 2200 lines of Python, driven end to end by the integration suite and
invisible to node's instrumentation; the report names that omission rather than
letting one number imply more than it measures.

The integration suite runs a real restic binary against a throwaway local
repository and asserts the round trip: backup, thin, restore, byte-for-byte
comparison — plus the exit-code contracts the entire UI depends on. It skips
cleanly when restic is not installed.

`test:e2e` drives the plugin against a **stubbed** cockpit bridge: fast, needs no
Cockpit, and blind to everything only the real bridge does. `test:ui` logs into a
running Cockpit and drives the same screens through the real one. That
distinction is not academic — the stub answered every call the folder picker made
while the picker listed nothing at all on a real machine, because
`cockpit.spawn`'s text channel discards output containing NUL bytes and the stub
happily carried them. It needs credentials and skips (exit 2) without them:

```sh
COCKPIT_PASS=… npm run test:ui        # or COCKPIT_URL / COCKPIT_USER
```

Rather than passing a password on every command line, point
`COCKPIT_CREDENTIALS_FILE` at a JSON file **outside the repository**, so it can
never be committed:

```sh
export COCKPIT_CREDENTIALS_FILE="$HOME/cockpit-credentials.json"
```

```json
{
  "host": "https://localhost:9090",
  "user": "your-login",
  "password": "your-password"
}
```

`chmod 600` it. When the variable is unset, `~/cockpit-credentials.json` is used
if it exists. Environment variables win over the file, so `COCKPIT_PASS=…` still
overrides it for a one-off run. With neither, the suite **skips** rather than
fails — a missing password is not a broken plugin.

---

## Known limitations

Stated plainly, because a backup tool that oversells itself is worse than one
that does less.

**Backing up a running database's files can produce a backup that will not
restore.** Hangar warns when a container that looks like a database is backed up
with consistency `none`, but no warning makes a live copy safe. For databases
use `stop`, or `command` with a real dump (`mongodump`, `pg_dump`).

**One machine.** Hangar manages the host it runs on. Cockpit's host switcher has
been deprecated and disabled by default since Cockpit 322, for sound security
reasons, so Hangar deliberately does not build on it. If you want several
machines in one view, point them all at **one shared restic repository** —
concurrent writers are safe and every snapshot records its hostname, so the
aggregation happens in the data rather than in the browser.

**Jottacloud cannot be configured from Hangar**, and several cloud providers
carry rate limits that are not Hangar's to fix. See
[Per-provider limits](#per-provider-limits).

**restic and rclone are not Red Hat–supported on RHEL.** They live in EPEL.

**No cross-run analytics.** Hangar has no database, so it can only show what
systemd and restic can tell it. Once journald rotates, that history is gone.

## Licence

See [LICENSE](LICENSE).
