# isolated-env

## Invariant

One documented command brings a clean checkout to a working environment, and
two environments built that way can exist on the same machine at the same
time without interfering. Concretely: no fixed port, no shared mutable path
outside the checkout, no step that installs or mutates something global, and
no database, cache, or socket a concurrent instance can corrupt.

The concurrency half is the part that matters and the part usually skipped.
Any setup script works once on a clean machine; the failures this invariant
prevents are two agents on one host, or two checkouts of the same project,
silently sharing state and producing results that cannot be reproduced or
attributed.

If this project has no runtime and no toolchain — a repository of documents,
for instance — the honest action is to delete this card and its row in
`docs/capabilities/index.md`, and to record the omission in `GOALS.md` under
scope. Keeping a card that is trivially satisfied manufactures a green check
that means nothing.

## Enforcement point

Continuous integration runs the setup command in two independent workspaces
concurrently, then runs the cheap verification command in each while the other
is still live. Failure refuses the change. Locally, the same procedure is run
by hand before any change to the setup path is merged.

## Acceptance

Passing case: clone the repository into two directories, run the documented
setup command in both at the same time, and observe both complete
successfully. While both environments are live, run the project's cheap
verification command in each and observe both pass. Record the two commands
and the observed exit statuses.

Failing case: introduce a fixed resource — bind a constant port, or write
state to a constant path such as `/tmp/<project>.sock` — then repeat the
concurrent run and observe the second instance fail with a message naming the
conflicting resource. Revert and observe the concurrent run pass again. This
is the case that gates promotion to `built`: a setup command that has only
ever been run once has not been shown to be isolated.

## Remediation message

    isolated-env: instance B failed to start — TCP port 5432 is already
    bound by instance A (<path of A's checkout>).
    Environments must not claim fixed resources. Allocate the port
    dynamically and read it from <the project's env var>, or move the
    resource inside the checkout.

The message names which instance failed, the exact resource in conflict, who
holds it, and the two legitimate fixes. "Port already in use" leaves the
reader to discover that concurrency was the point.

## Per-stack hints

Per-checkout virtual environments (`uv`, `venv`, `node_modules`) satisfy this
almost by construction; global installs never do. `nix develop` or a
devcontainer gives reproducibility as well as isolation. With
`docker compose`, set a project name derived from the checkout path so
containers, networks, and volumes cannot collide. Prefer a file-backed
database inside the checkout over a shared server, and bind port 0 to let the
operating system pick, then publish the chosen port through an environment
variable or a file in the checkout.
