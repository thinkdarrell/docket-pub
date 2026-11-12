# 0091 — www.docket.pub redirects to the apex at Cloudflare's edge, not through a Railway custom domain and a Flask redirect.

## Decision

`www.docket.pub` is a proxied CNAME in Cloudflare with no Railway custom domain behind it. A Cloudflare redirect rule answers every request to `www` with a 301 to the same path and query on `https://docket.pub`. The application never sees a `www` request and has no code for it.

## Rationale

Decision `0025` and debt `D10` planned the obvious alternative: a second Railway custom domain for `www`, a CNAME to it, and a redirect in Flask. That plan was written when DNS was at Namecheap and the only HTTPS terminator was Railway. On 2026-11-11 the apex moved behind Cloudflare's proxy (for a firewall rule against a scraper, `docs/specs/operations.md`), and from then on Cloudflare already held a certificate for `*.docket.pub` and could answer `www` itself. The Railway path would have added a domain to verify, a certificate to provision, a redirect to write and test in `src/docket/web/`, and a second place where host handling could go wrong, to produce the same 301. The edge rule costs one DNS toggle and one rule, and a `www` request no longer spends an origin round trip.

The cost is that the redirect lives in the Cloudflare dashboard and not in this repository; `docs/specs/operations.md` names it so an operator knows where to look. If docket.pub ever leaves Cloudflare's proxy, `www` stops working again until a redirect is provided elsewhere.

## Date

2026-11-12, the operator with Claude.

## Status

accepted
