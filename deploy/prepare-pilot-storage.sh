#!/bin/sh
# Administrator-run Linux example. Only NEW paths; never overwrites or formats an existing device.
set -eu
test "$(id -u)" = 0 || { echo "Run as the host administrator after reviewing this script." >&2; exit 1; }
test "$#" = 2 || { echo "Usage: prepare-pilot-storage.sh /private/new-org.img /private/new-mount" >&2; exit 1; }
image=$1
mountpoint=$2
case "$image:$mountpoint" in /*:/*) ;; *) echo "Use absolute paths." >&2; exit 1;; esac
test ! -e "$image" && test ! -L "$image" && test ! -e "$mountpoint" && test ! -L "$mountpoint" || { echo "Both paths must be new; nothing was changed." >&2; exit 1; }
umask 077
set -C
: > "$image"
set +C
truncate -s 512M "$image"
mkfs.ext4 -q "$image"
mkdir -m 700 "$mountpoint"
mount -o loop,nodev,nosuid,noexec "$image" "$mountpoint"
chown 10001:10001 "$mountpoint"
chmod 700 "$mountpoint"
echo "Created a private512MiB filesystem. Configure encrypted host storage/backups and a persistent mount; this script does not set encryption or automatic mounts."
