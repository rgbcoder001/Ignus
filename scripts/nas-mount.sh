#!/usr/bin/env bash
# Mounts a NAS share over NFS and keeps it mounted across reboots.
#
# Ignis supplies these as shell variables, from the answers the user gave:
#   nas_host    - the NAS address, e.g. 192.168.1.50
#   export_path - the NFS mount path on the NAS, e.g. /volume1/Media
#   mount_point - where it appears locally, e.g. /mnt/nas
#
# Writes a systemd .mount/.automount pair rather than an /etc/fstab line: a
# malformed fstab entry is a genuinely nasty failure for someone who is not
# comfortable at a terminal, and removing this later means deleting our own
# two files rather than editing one the boot depends on.
#
# The share is mounted on first access rather than at boot, so a NAS that is
# switched off, asleep or moved cannot delay or block startup.
#
# Safe to run more than once.
set -euo pipefail

: "${nas_host:?No NAS address was provided}"
: "${export_path:?No export path was provided}"
: "${mount_point:?No mount point was provided}"

case "$mount_point" in
    /*) ;;
    *) echo "The mount point must be an absolute path, like /mnt/nas." >&2; exit 1 ;;
esac
case "$export_path" in
    /*) ;;
    *)
        echo "The export path must be the NFS path on the NAS, starting with a" >&2
        echo "slash - for example /volume1/Media. Synology shows it at the" >&2
        echo "bottom of the NFS Permissions window." >&2
        exit 1
        ;;
esac

# Normalise a trailing slash so the checks below compare like with like.
mount_point="${mount_point%/}"
[ -z "$mount_point" ] && mount_point="/"

# Mounting over a system directory would hide it, which on some of these
# breaks the machine outright. Protect the user from a slip of the keyboard.
for forbidden in / /home /root /etc /usr /var /boot /bin /sbin /lib /lib64 \
                 /opt /srv /tmp /proc /sys /dev /run /mnt /media "$HOME"; do
    if [ "$mount_point" = "$forbidden" ]; then
        echo "Refusing to mount at ${mount_point} - that would hide an" >&2
        echo "important folder. Pick somewhere inside it instead, like" >&2
        echo "/mnt/nas." >&2
        exit 1
    fi
done

# A folder that already holds files would have them hidden by the mount.
# A folder that is already this mount (re-running) is fine.
if [ -d "$mount_point" ] && ! mountpoint -q "$mount_point" \
    && [ -n "$(ls -A "$mount_point" 2>/dev/null)" ]; then
    echo "${mount_point} already contains files. Mounting there would hide" >&2
    echo "them. Pick an empty location, like /mnt/nas." >&2
    exit 1
fi

UNIT_NAME="$(systemd-escape --path --suffix=mount "$mount_point")"
AUTOMOUNT_NAME="${UNIT_NAME%.mount}.automount"
UNIT_DIR="/etc/systemd/system"

echo "NAS         : ${nas_host}:${export_path}"
echo "Mount point : ${mount_point}"
echo "Unit        : ${UNIT_NAME}"
echo

# Check the export is actually visible before writing any units, so a typo
# produces a clear message now rather than a mount that silently never works.
if command -v showmount >/dev/null 2>&1; then
    echo "Checking the NAS is reachable..."
    if ! showmount -e "$nas_host" >/dev/null 2>&1; then
        echo "Could not list NFS shares on ${nas_host}." >&2
        echo "Check that NFS is enabled on the NAS, that this machine's IP is" >&2
        echo "allowed in the share's NFS Permissions, and that the address is" >&2
        echo "correct." >&2
        exit 1
    fi
    echo "NAS is reachable."
else
    echo "Skipping the reachability check (showmount is not installed)."
fi

MOUNT_UNIT="[Unit]
Description=NAS media at ${mount_point} (managed by Ignis)
After=network-online.target
Wants=network-online.target

[Mount]
What=${nas_host}:${export_path}
Where=${mount_point}
Type=nfs4
Options=rw,noatime,_netdev,vers=4.1

[Install]
WantedBy=multi-user.target
"

AUTOMOUNT_UNIT="[Unit]
Description=Automount NAS media at ${mount_point} (managed by Ignis)

[Automount]
Where=${mount_point}
TimeoutIdleSec=600

[Install]
WantedBy=multi-user.target
"

echo "Setting this up needs administrator rights, so a password box will appear."

# The -c body is single-quoted ON PURPOSE: nothing the user typed is ever
# interpolated into this root shell as code. Every value arrives as a
# positional argument and is only ever expanded inside double quotes as data.
# (An earlier version interpolated ${mount_point} directly, which let a
# crafted mount point break out of its quoting and run as root.)
pkexec /usr/bin/bash -c '
set -euo pipefail
mount_unit="$1"; automount_unit="$2"; target="$3"; unit_file="$4"; automount_file="$5"
unit_dir=/etc/systemd/system
mkdir -p "$target"
printf "%s" "$mount_unit" > "${unit_dir}/${unit_file}"
printf "%s" "$automount_unit" > "${unit_dir}/${automount_file}"
chmod 0644 "${unit_dir}/${unit_file}" "${unit_dir}/${automount_file}"
systemctl daemon-reload
systemctl enable --now "$automount_file"
' _ "$MOUNT_UNIT" "$AUTOMOUNT_UNIT" "$mount_point" "$UNIT_NAME" "$AUTOMOUNT_NAME"

echo
echo "Checking the share responds..."
# Bounded: a hard NFS mount that stops answering would otherwise hang here
# forever, stuck behind a progress dialog with no way out.
if timeout 20 ls "$mount_point" >/dev/null 2>&1; then
    echo "Mounted. Your NAS is available at ${mount_point}"
    echo
    echo "Open it in Files, or point an app at that folder. It will connect"
    echo "on its own whenever something reads it, and will not hold up"
    echo "startup when the NAS is switched off."
else
    echo "The units are installed, but reading ${mount_point} did not work." >&2
    echo "Check the NFS Permissions for this machine's IP on the NAS." >&2
    exit 1
fi
