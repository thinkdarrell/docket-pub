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
#
# Refusals (exit 3, before COMMIT_SHA is written or railway is invoked):
# a working tree with uncommitted changes (`git status --porcelain` not
# empty; a COMMIT_SHA left by a dead run counts), then a branch other
# than main. Deploys run from a clean main after the pull request has
# merged (GOALS.md Constraints, decision 0022). Exit 2 is bad usage.

set -euo pipefail

if [ $# -lt 2 ] || [ "$1" != "--service" ]; then
    echo "usage: scripts/deploy.sh --service <docket-web|worker> [extra railway up flags]" >&2
    exit 2
fi

cd "$(git rev-parse --show-toplevel)"

branch=$(git rev-parse --abbrev-ref HEAD)
sha=$(git rev-parse HEAD)
service="$2"

if [ -n "$(git status --porcelain)" ]; then
    echo "deploy: refusing to deploy with uncommitted changes (git status --porcelain is not empty): railway up ships the working tree as it is. Commit, stash, or remove them (a COMMIT_SHA left by a dead run counts) and re-run." >&2
    exit 3
fi

if [ "$branch" != "main" ]; then
    echo "deploy: refusing to deploy from branch '$branch': deploys run from a clean main after the pull request has merged (GOALS.md Constraints, decision 0022)." >&2
    exit 3
fi

echo "Deploying $service at $sha..."
echo "$sha" > COMMIT_SHA
trap 'rm -f COMMIT_SHA' EXIT

railway up "$@" --detach
