#!/bin/sh
set -eu
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump -Fc -U taskmate taskmate > "/backup/taskmate-${stamp}.dump"
find /backup -name 'taskmate-*.dump' -mtime +14 -delete
