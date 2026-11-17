# Backup

As of 2026-11-17 the freshest complete git history is copied to a second
physical disk as well as this one:

- `seo-agent-backup-20261117-p4.bundle` — full history (`--all`) at commit
  `3fa6042` (Phase 4 live run + fixture H2 fix, N-20). Verified 2026-11-17
  with `git bundle verify` ("okay", complete history). On this disk and on
  `/mnt/backup/seo-agent-backups/`.
- `seo-agent-backup-20261117-p3.bundle` — full history at `48f3811`
  (Phase 3 implementation). On this disk and on `/mnt/backup/seo-agent-backups/`.
- `seo-agent-backup-20261117.bundle` — older snapshot, kept untouched. Also copied.

**Off-site copy landed 2026-11-17: master was pushed to `origin`
(`git@github.com:kibria-miran/seo-agent.git`, private) over SSH. GitHub now
holds the full history off this machine; the rclone `terabox:` remote remains
unused.**

Off-machine status: `/mnt/backup` is a separate 298 GB disk mounted on this
same machine (not a remote, not a USB stick taken elsewhere). It covers
failure of the root disk; it does NOT cover fire, theft, or machine loss.
GitHub `origin` is the off-site copy; keep it current with `git push`.

To restore from the bundle:

    git clone seo-agent-backup-20261117-p4.bundle seo-agent

To restore from GitHub instead of a bundle:

    git clone git@github.com:kibria-miran/seo-agent.git seo-agent

To move the bundle off-site once any other destination exists:

    cp /mnt/backup/seo-agent-backups/seo-agent-backup-20261117-p4.bundle /media/<usb>/
    # or: gpg -c seo-agent-backup-20261117-p4.bundle && upload the .gpg

Update this file whenever a newer bundle is made or an off-site copy lands;
it is the pointer a disk-recovery reader needs.
