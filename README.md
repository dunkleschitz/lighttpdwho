# lighttpdwho

Which lighttpd condition block sets a configuration key for this
request — and at which file:line?

`lighttpd -t` validates a config; it never answers selection
questions. `lighttpd -p` prints the parsed config in internal form —
flattened, optimized, and provenance-free: includes already expanded,
identical condition blocks already merged, variables already
substituted, no file:line attached to anything, and the per-request
selection left for the reader to simulate by hand. Worse, obtaining
that output requires the daemon to evaluate `include_shell`, i.e. to
*execute shell commands from the config* with the invoking user's
environment. grep prints every candidate line and adjudicates none
of them — and it cannot see that the answer lives at the end of an
include chain whose relative paths resolve against the *main* file's
directory, inside condition scopes whose selection rule is
last-matching-wins with *no* cross-scope merging, behind `else`
chains that are not independent negations and a `global {}` escape
hatch that lifts assignments out of the conditional they textually
sit in. `lighttpdwho` is a static model of lighttpd's documented
config-selection rules that answers the question with file:line
provenance, and says UNKNOWN (naming the blocker) whenever the
answer is not statically knowable.

## Usage

```
lighttpdwho KEY [--host H] [--url P] [--scheme S] [--method M]
                [--querystring Q] [--remoteip IP] [--socket SOCK]
                [--header 'Name: value']... [--env K=V]...
                [--cwd DIR] [--conf FILE]...
lighttpdwho --list-conditions [--conf FILE]...
lighttpdwho --list-keys [--conf FILE]...
```

- `KEY` is a top-level option name (`server.document-root`,
  `url.access-deny`, `ssl.engine`, `fastcgi.server`). Keys are
  top-level only; what a module does internally with the selected
  value is the module's business.
- Request fields are optional individually, but a field the config
  *tests* and the query omits is UNKNOWN — the tool never defaults a
  field the operator did not supply. There are no exceptions:
  `--scheme` is never defaulted either.
- `--host` is the authority as given; `--url` is the path only (no
  host, no query string); `--querystring` is the part after `?`
  (supply an empty string for a request with no `?` — only an
  *unsupplied* `--querystring` is UNKNOWN); `--remoteip` is the peer
  address as the daemon sees it (not `X-Forwarded-For`); `--socket`
  is the listening socket (`ip:port`, or a unix-domain path).
- `--header` is repeatable (`--header 'Name: value'`); the header
  *name* is case-insensitive and last wins per name. A header absent
  from the supplied request is the empty string for `==`-family
  tests.
- `--env K=V` supplies the daemon's startup environment, the only
  source for `env.NAME` — the tool never reads its own environment.
  `--cwd DIR` supplies the directory the daemon was started in (for
  `var.CWD`); without it, `var.CWD` renders `<CWD-unknown>`.
- `--conf` is repeatable; files are concatenated in the order given
  (a lighttpdwho convenience — the daemon takes one `-f` file;
  relative-include resolution for each root is against *that*
  root's directory, bannered in coverage). Default:
  `/etc/lighttpd/lighttpd.conf` if it exists, else exit 2.
- `--list-conditions` lists every conditional block in document
  order, with header file:line, field/op/value, nesting path,
  else-chain position, merged-sibling notes, and the keys assigned
  inside. `--list-keys` lists every assigned key with its
  assignment count by scope kind and first/last file:line.
- `--json` renders the same structure machine-readably; `--quiet`
  prints the verdict line only; `--version` prints the version.

## Examples

```bash
# Which document-root does host a.example get?
lighttpdwho server.document-root --host a.example \
  --conf /etc/lighttpd/lighttpd.conf
# EFFECTIVE
# decider: /etc/lighttpd/vhosts/a.conf:3 ($HTTP["host"] == "a.example"
#   at /etc/lighttpd/lighttpd.conf:12) -- server.document-root = "/var/a"
# value: "/var/a"

# Same query, machine-readable
lighttpdwho server.document-root --host a.example --json \
  --conf /etc/lighttpd/lighttpd.conf

# The LT09 footgun: a conditional `+=` does NOT extend the root list
# -- the conditional scope's value stands alone
lighttpdwho server.modules --host a.example \
  --conf lighttpd.conf
# EFFECTIVE
# decider: lighttpd.conf:4 ($HTTP["host"] == "a.example" at
#   lighttpd.conf:3) -- server.modules = ( "mod_b" )
# value: ( "mod_b" )

# The LT13 hazard, caught: the else attaches to the b.example block,
# so for host a.example the else branch -- not the a.example block --
# is the last matching scope
lighttpdwho server.document-root --host a.example \
  --conf else-trap.conf
# EFFECTIVE
# decider: else-trap.conf:9 (else-branch 1 (else) at else-trap.conf:8)
#   -- server.document-root = "/var/other"

# What does the config actually contain?
lighttpdwho --list-conditions --conf /etc/lighttpd/lighttpd.conf
lighttpdwho --list-keys --conf /etc/lighttpd/lighttpd.conf
```

## Verdicts

| Verdict | Meaning | Exit |
|---|---|---|
| `EFFECTIVE` | The key's effective value, with the decider's file:line | 0 |
| `NOT-SET` | No assignment to the key applies to this request | 1 |
| `UNKNOWN` | A blocker (named) prevents a static answer | 1 |

Every run also prints a candidate chain (every assignment to the key
in precedence order with its scope verdict TRUE/FALSE/UNKNOWN and
file:line), findings, an unmodeled inventory (`include_shell` lines,
`env`-unknown references, `[regex-unknown]` patterns), and a coverage
section (files read with byte/line counts, include directives with
resolved paths and expansion kinds, scopes defined, keys assigned,
gated/UNKNOWN-scope assignments for this key, `env.`/`var.PID`/
`var.CWD` dependencies, unparseable lines).

## Pinned semantics (LT01–LT27, see DESIGN-lighttpdwho.md)

- **LT01** Per-key config selection, not request handling. A key with
  no applicable assignment is `NOT-SET`; the daemon/module default is
  never invented.
- **LT02** Include chain: textual in-place insertion in the enclosing
  scope; missing literal include and include cycles are fatal (exit 2).
- **LT03** Relative includes resolve against the MAIN config file's
  directory, not the including file's — the opposite of keepalived's
  rule, and the single most likely loader bug. A finding is raised
  whenever a relative include is followed from a file in a different
  directory.
- **LT04** Include globs expand in byte-wise sorted order; a glob
  matching nothing is a warning, and a `NOT-SET` answer over an empty
  glob lists it as `[possibly-missing]`.
- **LT05** `include_shell` is NEVER executed. It is inventoried
  verbatim and poisons positionally: absorbed by a later TRUE decider,
  otherwise the verdict is UNKNOWN with the shell line as blocker.
- **LT06** `global { }` lifts assignments to root scope, at their
  stream position among root assignments.
- **LT07** `var.`/`env.` are parse-time and sequential. `var.PID`
  renders `<PID-unknown>`; `var.CWD` resolves only from `--cwd`;
  `env.` comes only from `--env`. A use before definition is an
  unparseable finding, never an empty-string guess.
- **LT08** Assignment operators are scope-local: `=` assigns, `+=`
  merges onto the same scope's earlier value, `:=` replaces. A
  duplicate `=` in one scope is shadowed by the later line.
- **LT09** Last matching condition wins; NOTHING merges across scopes.
  A conditional assignment replaces the root value whole — arrays
  included. The Apache/nginx intuition (inherit-and-extend) is exactly
  wrong here.
- **LT10** Conditional fields/operators/version gates; legacy header
  aliases (`$HTTP["cookie"]`, `["useragent"]`, `["language"]`,
  `["referer"]`) normalize to `$REQUEST_HEADER[...]` with a banner.
- **LT11** No AND/OR operators. A header with `&&`/`||` is
  unparseable.
- **LT12** Nesting is AND; the nested scope is later in precedence.
- **LT13** Else/elif chains short-circuit: a branch matches iff all
  previous branches are FALSE and its own test is TRUE; a previous
  UNKNOWN makes later branches UNKNOWN; `else` attaches only to the
  immediately preceding block in the same file.
- **LT14** Identical conditions at one level are merged at parse time;
  assignments from both textual blocks are considered in document
  order, with a merge finding.
- **LT15** Precedence: root is the base layer, then matching scopes in
  depth-first document order. A root line textually after a conditional
  never shadows it for a matching request.
- **LT16** `$HTTP["host"]` is the authority as given; `==`/`!=`/`=^`/`=$`
  are case-insensitive, regexes run on the lowercased host. A host
  regex anchored at the end without a port allowance raises the
  `[host-regex-port-trap]` finding.
- **LT17** `$HTTP["remoteip"]` is the peer address; CIDR only for
  `==`/`!=`. With `mod_extforward` loaded and a remoteip test in the
  decider chain, the `[peer-ip-may-be-rewritten]` banner is raised.
- **LT18** url/querystring/scheme/method/headers. An absent header is
  the empty string; only a query field the operator did not supply is
  UNKNOWN. URL normalization before matching is not reproduced
  (`[url-normalization-not-modeled]`).
- **LT19** Regexes are PCRE; Python `re` is a subset, never an
  approximation. Unsupported constructs (lookbehind, possessive
  quantifiers, `\z`, `\K`, conditional patterns, PCRE-only classes)
  are `[regex-unknown]` (UNKNOWN); invalid patterns poison their scope.
- **LT20** `$SERVER["socket"]` is evaluated against `--socket` as
  written, with omitted-IP expansion (`:80` is `0.0.0.0:80`); a socket
  scope with no `--socket` is UNKNOWN.
- **LT21** Three-valued (Kleene) evaluation. The last TRUE-scope
  assignment is the decider unless an UNKNOWN-scope assignment sits
  after it in precedence order; UNKNOWN-scope assignments before the
  decider are absorbed with findings.
- **LT22** Verdict vocabulary: `EFFECTIVE` (exit 0), `NOT-SET`
  (exit 1), `UNKNOWN` (exit 1). `--quiet` prints the verdict line only.
- **LT23** Unparseable lines poison the selected answer positionally;
  one broken vhost must not blind the tool to the other forty.
- **LT24** Values are opaque, rendered as selected. `%0`–`%9` / `$0`–`$9`
  / `${url.*}` tokens are rendered verbatim, never evaluated, with a
  `[capture-substitution-not-evaluated]` finding.
- **LT25** Runtime vhost modules (`mod_simple_vhost`, `mod_evhost`,
  `mod_vhostdb`, `mod_mysql_vhost`, `mod_magnet`) make
  `server.document-root` UNKNOWN, even when a conditional assignment
  exists; for other keys their presence is a banner only.
- **LT26** Safety: pure text parsing; no subprocess, no network, no
  writes, no environment reads. The only value printed is the queried
  key's selected value.
- **LT27** Coverage on every run: files read, includes, scopes, keys,
  gated assignments, dependencies, unparseable lines.

## Limitations

- **LT05** — `include_shell` output is statically unknowable. The
  tool inventories the command verbatim and never runs it; any key
  whose decider could live in shell output is UNKNOWN unless a later
  known assignment overrides it.
- **LT09/LT15** — the last-matching-wins, no-cross-scope-merge rule is
  the tool's reason to exist and its sharpest edge: a root assignment
  textually after a conditional never shadows it for a matching
  request, and a conditional `+=` never extends the root list. Read
  the candidate chain.
- **LT19** — PCRE is not Python `re`. Patterns past the common subset
  are `[regex-unknown]` and make the test UNKNOWN, never a guess.
- **LT25** — runtime vhost modules decide `server.document-root` from
  filesystem/database state the files cannot show. With one loaded,
  the answer is UNKNOWN, not the conditional assignment.
- **LT13** — an `else` attaches only to the immediately preceding
  block in the same file. Whether the daemon attaches across an
  include boundary is an open question; v1 does not.
- **LT04** — glob order is pinned to byte-wise sorted (the glob(3)
  convention); the daemon's C glob under a non-C locale may differ.
- **LT15/LT09** — root-vs-conditional precedence is pinned to the
  structural reading (root is always the base layer) and conditional
  `+=` to the literal Merging-section reading (`+=` over empty in the
  conditional scope). Both are flippable hypotheses; a live
  contradiction flips the rule, not the finding. See the design doc's
  open questions.
- Runtime state can diverge from the files; every verdict is on-disk
  config selection.
- `lighttpdwho` is **not a validator**: `lighttpd -t` remains the
  validation path. Real lighttpd refuses to start on any syntax error;
  lighttpdwho degrades — broken blocks it was not asked about are
  warning findings, and only defects that can change *this key's*
  answer poison the verdict to UNKNOWN. One broken vhost must not
  blind the tool to the other forty. The exceptions are load failures
  — missing literal include and include cycles — which are fatal
  (exit 2) because the daemon would not load the config at all.

## Out of scope

- **Request handling** — rewriting, redirecting, backend selection,
  access decisions (LT01).
- **Module-internal config use** — how a module merges or interprets
  the selected value beyond LT09's selection rule (LT24), except the
  LT25 document-root override.
- **Runtime vhosting** — simple_vhost/evhost/vhostdb/magnet results
  (LT25); **filesystem state** — whether a document-root or backend
  socket exists.
- **include_shell output** (LT05) and **daemon environment** beyond
  `--env` (LT07).
- **URL normalization** before url matching (LT18) and
  **forwarded-peer substitution** (LT17).
- **The running daemon's state** — loaded-vs-disk honesty: every
  verdict is labeled on-disk config selection.

## Tests

94 tests (stdlib unittest, `python3 test_lighttpdwho.py`): core
selection, merging, fields and operators, nesting and else chains,
three-valued evaluation, includes, var/env/shell, regex, dynamism,
coverage, and safety. No lighttpd binary exists on the build box, so
there is no live-agreement test — fixture trees are the only oracle,
exactly as the manual text is the only authority.

## Pre-publish checklist

- [x] Tests green (94/94)
- [x] Dogfood: doccover + clicheck clean (Nov 9 campaign: clicheck 15/15, doccover 16/16, 0 gaps)
- [x] Bench-audit map extended (Nov 9 campaign: added to audit.py TOOLS map; A1–A7 re-run via the audit's own functions, 7 checks, 0 findings; tests re-verified 94/94)
- [ ] Local commit (separate campaign step)
- [ ] README + CHANGELOG in place (LICENSE (MIT) + CI workflow are
      prepublish-check items, separate campaign step)
- [ ] Prepublish-check clean (separate campaign step)
- [ ] Publish: **NOT covered by the Nov 9 campaign pre-approval**
      (that names only haproxywho/squidwho/keepalivedwho) — needs
      Sam's explicit per-project approval. Do NOT publish, set a
      remote, or push without it.

## License

MIT — see LICENSE (added at prepublish-check).
