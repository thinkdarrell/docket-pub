#!/usr/bin/env bash
# scripts/deploy.sh — wrap `railway up` to stamp the current HEAD SHA
# into /app/COMMIT_SHA so future code-parity audits can run
# `railway ssh --service <svc> "cat /app/COMMIT_SHA"`.
#
# Railway CLI excludes .git from `railway up` uploads, so we can't run
# `git rev-parse HEAD` from inside the Dockerfile. Instead, write the
# SHA to a tracked-but-gitignored file before upload; the Dockerfile
# moves it into place during build.
#
# Usage:
#   scripts/deploy.sh --service docket-web
#   scripts/deploy.sh --service worker
#   scripts/deploy.sh --service docket-web --environment production
#
# Always runs `railway up --detach` (per docket.pub deploy norm); pass
# any additional flags after --service.

set -euo pipefail

if [ $# -lt 2 ] || [ "$1" != "--service" ]; then
    echo "usage: scripts/deploy.sh --service <docket-web|worker> [extra railway up flags]" >&2
    exit 2
fi

cd "$(git rev-parse --show-toplevel)"

branch=$(git rev-parse --abbrev-ref HEAD)
sha=$(git rev-parse HEAD)
service="$2"

if [ "$branch" != "main" ]; then
    echo "WARNING: deploying from non-main branch '$branch' — docket.pub norm is to deploy from main." >&2
    echo "         (continuing in 3s; Ctrl-C to abort)" >&2
    sleep 3
fi

echo "Deploying $service at $sha..."
echo "$sha" > COMMIT_SHA
trap 'rm -f COMMIT_SHA' EXIT

railway up "$@" --detach
