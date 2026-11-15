#!/bin/sh
# Runs as root just long enough to give the data volume to the app user,
# then replaces itself with the server running as that user.
set -eu
chown -R app:app /data
export HOME=/home/app  # setpriv changes the user, not the environment
exec setpriv --reuid=app --regid=app --init-groups "$@"
