# Backup

As of 2026-11-17 the freshest complete git history is on this disk only:

- `seo-agent-backup-20261117-p3.bundle` — full history (`--all`) at commit
  `48f3811` (Phase 3 implementation). Verified 2026-11-17 with
  `git bundle verify` ("okay", complete history).
- `seo-agent-backup-20261117.bundle` — older snapshot, kept untouched.

Neither has been copied off this machine (no remote destination, no USB
confirmed). If the disk fails, three commits of Phase 2/3 work go with it.

To restore from the bundle:

    git clone seo-agent-backup-20261117-p3.bundle seo-agent

To move it off-machine once any destination exists:

    cp seo-agent-backup-20261117-p3.bundle /media/<usb>/
    # or: gpg -c seo-agent-backup-20261117-p3.bundle && upload the .gpg

Update this file whenever a newer bundle is made or an off-machine copy
lands; it is the pointer a disk-recovery reader needs.
