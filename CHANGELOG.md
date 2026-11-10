# CHANGELOG — lighttpdwho

## 1.0.0 (2026-11-09)

Initial release. Static model of lighttpd's documented config-selection
rules (Docs_Configuration, lighttpd(8), 1.4.46–1.4.82): which condition
block sets a configuration key for a request, and at which file:line.

LT01 per-key config selection, never request handling; NOT-SET instead
of invented defaults; LT02 include chain with textual in-place
insertion, missing literal include and include cycles fatal (exit 2);
LT03 relative includes resolve against the main config file's
directory, with a finding when followed from a different directory;
LT04 include globs in byte-wise sorted order, empty glob a warning
with [possibly-missing] on NOT-SET; LT05 include_shell never executed,
inventoried verbatim, poisoned positionally; LT06 global { } lifts
assignments to root scope at stream position; LT07 var./env. parse-time
and sequential, var.PID/var.CWD rendered as placeholders, env. only
from --env, use-before-definition an unparseable finding; LT08
scope-local =, +=, := with shadowed-duplicate findings; LT09 last
matching condition wins, nothing merges across scopes; LT10 conditional
fields/operators/version gates with legacy header-alias normalization;
LT11 no AND/OR, boolean operators in a header are unparseable; LT12
nesting is AND with the nested scope later; LT13 else/elif chains
short-circuit with previous-branch-UNKNOWN propagation and
same-file-only attachment; LT14 identical conditions merged at parse
time; LT15 root as the structural base layer, matching scopes in
depth-first document order; LT16 host authority/port/case rules with
the [host-regex-port-trap] finding; LT17 remoteip CIDR for ==/!=, peer
not client, mod_extforward banner; LT18 url/querystring/scheme/method/
headers with omitted fields UNKNOWN, never defaulted; LT19 PCRE as a
Python `re` subset, never an approximation ([regex-unknown] for
unsupported constructs, invalid patterns poison); LT20 $SERVER["socket"]
with omitted-IP expansion; LT21 Kleene three-valued evaluation with
absorbed-UNKNOWN findings; LT22 EFFECTIVE / NOT-SET / UNKNOWN with
exits 0/1/2; LT23 unparseable lines poison positionally; LT24 values
opaque with capture tokens rendered verbatim; LT25 runtime-vhost
modules make server.document-root UNKNOWN; LT26 pure text parsing, no
subprocess/network/writes/environment reads; LT27 coverage on every
run; --list-conditions and --list-keys inventory modes; --json, --quiet,
--version.

Build note: 94-test hermetic suite (BG1–BG9) green. Publishing is NOT
covered by this release — lighttpdwho was not among the Nov 9 campaign's
three pre-approved tools; it follows the normal per-project approval
path.
