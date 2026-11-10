# lighttpdwho — hazard-first design review

**Status:** BUILD APPROVED (2026-11-09).
**Question:** for one configuration key (e.g. `server.document-root`,
`url.access-deny`, `ssl.engine`) and one fully specified request,
which assignment in lighttpd.conf plus its include tree is the
*effective* one — i.e. the assignment in the last matching scope —
and at which file:line does it live?
**Shape:** `lighttpdwho KEY [--host H] [--url P] [--scheme S]
[--method M] [--querystring Q] [--remoteip IP] [--socket SOCK]
[--header 'Name: value']... [--env K=V]... [--cwd DIR]
[--conf FILE]...` over lighttpd.conf plus its `include` tree.
Flags (who-family standard): `--json`, `--quiet`, `--version`,
plus `--list-conditions` and `--list-keys`.
**Pinned from:** Docs_Configuration, lighttpd redmine (current,
read 2026-11-09 — BNF syntax, conditional configuration, the
Conditional Configuration Merging section, Using variables,
Limitations, Global context); lighttpd(8), Debian/Ubuntu
(`-f`, `-p`, `-t`, `-tt`); lighttpd forum exchange on
include/include_shell relative-path resolution (gstrauss,
2022-12, confirming relative resolution against the main config
file's directory); lighttpd issue activity noting `include` glob
support (fix for #1221) and the if-else short-circuit fix for
#2598. Semantics pinned to the lighttpd 1.4.46 – 1.4.82 range
(1.4.82 is the current stable line, Sep 2025); version-gated
grammar differences are called out where they appear (LT10).
No lighttpd binary exists on this box (`lighttpd` is not
installed) and no live experiments were run, so every claim
below is `[documented]` (the docs/man page above),
`[docs-inferred]` (follows from a documented rule), or
`[hypothesized]` (best-supported guess, flippable) — never
`[observed]`. There is no live-agreement test to skip-guard
against in v1: `lighttpd -p` prints a parsed form, but producing
it executes the config's `include_shell` commands (LT05), so it
is not a safe oracle for arbitrary configs; fixture trees are
the oracle, exactly as the manual text is the only authority. A
claim that turns out wrong must flip the design, not get quietly
absorbed.

## Thinness verdict: APPROVED, and no native holder answers the question

1. **`lighttpd -t` / `-tt` validate; they do not adjudicate.**
   They answer "does this parse (and do the modules load)",
   never "for Host X and URL /admin, which `url.access-deny`
   assignment wins, and where is it written" [documented —
   lighttpd(8)].
2. **`lighttpd -p` prints the parsed config in internal form —
   flattened, optimized, and provenance-free.** Includes are
   already expanded, identical condition blocks already merged
   (LT14), variables already substituted, no file:line attached
   to anything, and the per-request selection (last matching
   condition, LT09/LT15) is left for the reader to simulate by
   hand over the printed scopes [documented — lighttpd(8): `-p`
   prints "the parsed configuration file in its internal
   form"]. Worse, obtaining that output requires the daemon to
   evaluate `include_shell`, i.e. to *execute shell commands
   from the config* (LT05) with the invoking user's environment
   — a provenance tool must never do that to answer a question.
3. **grep cannot do this at all.** The answer lives at the end
   of an include chain (LT02) whose relative paths resolve
   against the *main* file's directory, not the including
   file's (LT03), inside condition scopes whose selection rule
   is last-matching-wins with *no* cross-scope merging (LT09),
   behind `else` chains that are not independent negations
   (LT13) and a `global {}` escape hatch that lifts assignments
   out of the conditional they textually sit in (LT06). Grep
   prints all the candidate lines and adjudicates none of it.

If the build cannot reproduce LT09 (last-matching wins, `+=`
does not cross scopes), LT12/LT13 (nesting is AND; else chains
short-circuit and are never re-read as independent `!=` tests),
and LT05 (include_shell poisons, never executes) against
fixture trees, it does not ship — those three are the tool's
reason to exist.

## Pinned semantics

### Files and lines

- A config is a sequence of assignments, `var.` definitions,
  `include` / `include_shell` directives, `global { }` blocks,
  and conditional blocks, in one merged stream (LT02).
  Comments start with `#` to end of line [documented — the
  conventional syntax throughout the docs; a `#` inside a
  quoted string is literal]. Option names are
  `modulename.key` [documented BNF]; v1's recognizer accepts
  any dotted name of that shape. Values are string / integer /
  boolean (`enable|disable|1|0`) / array — value lists
  `( v, ... )` and key lists `( "k" => v, ... )`, nestable —
  and expressions built with `+` from stringifiable values
  [documented BNF].
- **LT00 — tokenizer:** braces, parentheses, `=>`, the
  assignment operators (`=`, `+=`, `:=`), commas, and `{`/`}`
  block structure must tokenize across line breaks (arrays and
  conditions routinely span lines); a conditional header is
  `FIELD OP VALUE {` on one logical line, optionally preceded
  by `if` / followed by an `else` chain (LT13). Quoted strings
  may be built by `+`-concatenation of literals, `var.`, and
  `env.` references [documented BNF: a string "can be
  constructed from multiple stringifiable values"].

### LT01 — Verdict scope: per-key config selection, not request handling [design rule]

lighttpdwho answers *which assignment the daemon's static
config selection would apply for this key and this request*,
never *what the daemon will do with the request*. Consequences:

- It never follows a rewrite/redirect, never checks whether a
  document-root exists, never evaluates a backend, and never
  claims a request is allowed or denied — an effective
  `url.access-deny = ( "" )` is reported *as the effective
  assignment*, with provenance, not as a DENIED verdict.
- Keys are top-level option names only (`fastcgi.server`, not
  paths inside its array). What a module does internally with
  the selected value is the module's business (LT24/LT25).
- A key with no applicable assignment is `NOT-SET` (LT22):
  the daemon default for most keys lives in the module, not
  the config, and the tool never invents a default value.

### LT02 — Loading model: the include chain [documented + docs-inferred]

- `include <string>` inserts the referenced file's content
  *textually, in place, at the point of the directive*, in
  whatever scope encloses the directive [docs-inferred — the
  docs' own examples include files inside a
  `$HTTP["host"] == ... { }` block and the included assignments
  are that host's configuration; and inside the global file
  scope]. An include inside a conditional therefore contributes
  *conditional* assignments (LT06 is the documented escape);
  an include inside an `else` block contributes else-scope
  assignments; nesting depth of the included content is the
  depth at the directive.
- Includes nest (an included file may include further files)
  with no documented depth limit; brace/scope balance is
  tracked across the merged stream.
- **Cycle detection:** an include cycle → fatal finding,
  exit 2 [design rule — the squidwho SQ19 lesson: a loader that
  cannot terminate cannot answer].
- A missing *literal* include file is fatal, exit 2
  [docs-inferred — the daemon cannot open the file and `-t`
  fails; there is no tree to answer over]. The glob no-match
  case is different (LT04).
- `--conf` may be repeated; files are concatenated in the
  order given (a v1 convenience — the daemon takes one `-f`
  file; relative-include resolution for each root is against
  *that* root's directory, bannered in coverage). Default
  discovery when `--conf` is absent:
  `/etc/lighttpd/lighttpd.conf` if it exists; else exit 2 with
  the searched path named — never a silent guess at another
  tree [documented default path — lighttpd(8)].

### LT03 — Relative includes resolve against the MAIN config file [documented]

- "include, relative to dirname of main config file"
  [documented — the BNF example's own comment], confirmed by
  the maintainer for both `include` and `include_shell`:
  relative paths "resolve relative paths against the directory
  of main configuration file" (forum, 2022-12). This is the
  opposite of keepalived's rule (relative to the *including*
  file) and the single most likely loader bug: a nested include
  `include "conf.d/x.conf"` inside `/etc/lighttpd/vhosts/a.conf`
  resolves to `/etc/lighttpd/conf.d/x.conf`, **not**
  `/etc/lighttpd/vhosts/conf.d/x.conf`. v1 resolves every
  relative include in the whole tree against the root `--conf`
  file's directory, and raises a finding whenever a relative
  include is followed from a file in a different directory
  (the AA10 lesson: the base is not what intuition says).
- A path beginning with `/` is taken as absolute as written
  [docs-inferred — every real-world example in the docs uses
  absolute glob includes such as `/etc/lighttpd/conf.d/*.conf`;
  an old bug report (#1698) claiming all paths are relative is
  treated as superseded by the documented examples].

### LT04 — include globs: `*` supported, order pinned, no-match is a finding [documented + design rule]

- The `include` string may contain a `*` wildcard
  [documented — glob support added for #1221; the stock
  examples include `"/etc/lighttpd/conf.d/*.conf"`]. v1 expands
  each pattern with Python `glob` and processes matches in
  byte-wise sorted order [hypothesized — the docs never state
  an order; sorted order is the glob(3) convention the daemon's
  C implementation inherits. The order matters only when two
  matched files set the same key in the same scope (LT15's
  document order), and the build pins sorted order with a
  fixture so a contradiction is a one-line flip].
- Only `*` is pinned. Patterns containing `?`, `[...]`, or a
  second path component with wildcards are expanded as Python
  glob expands them and bannered in coverage (the daemon's
  glob is the C library's; divergence here is an open
  question, LT-open).
- A glob pattern matching **nothing** is an empty expansion
  with a warning finding, not a fatal error [design rule —
  an empty `conf-enabled/` directory is a stock Debian idiom,
  not a broken config]. But: an empty expansion can hide a
  typo'd directory, so if the queried key is `NOT-SET` and any
  glob expanded empty, the answer lists the empty globs as
  `[possibly-missing]` candidates rather than presenting
  NOT-SET as clean.

### LT05 — include_shell is unmodeled dynamism, and is NEVER executed [documented + family rule]

- `include_shell <string>` "read configuration from output of
  a command" [documented BNF example]: the daemon runs the
  command at parse time and parses its stdout as config. The
  command string itself may be an expression
  (`include_shell "/usr/share/lighttpd/use-ipv6.pl " +
  server.port` is a stock line [documented in distro configs
  quoted in the docs' ecosystem]).
- This is the Debian ecosystem's dominant idiom —
  `include-conf-enabled.pl`, `create-mime.assign.pl`,
  `include_shell "cat /etc/lighttpd/vhosts.d/*.conf"` — so real
  configs routinely have a large, statically unknowable chunk.
  v1 **never spawns a subprocess** (test-asserted, family
  harness): the command is inventoried verbatim with file:line,
  never run, never `cat`-special-cased (a `cat` of a glob is
  shell state, not a file list the tool may substitute).
- **Poison rule (positional, Kleene):** an `include_shell`'s
  output is inserted at its point in its enclosing scope, so
  it can set any key for any request its scope matches. It
  poisons the verdict for a key exactly when a later-or-equal
  decider is not already guaranteed: if the last TRUE-scope
  assignment for the key (LT15) comes *after* the
  include_shell in precedence order, the include_shell is
  absorbed with a finding (its output was overridden by a
  known later value); if no such later assignment exists and
  the include_shell's scope is TRUE or UNKNOWN for this
  request, the verdict is `UNKNOWN` with the include_shell
  line as blocker. An include_shell in a FALSE scope is
  inventoried and harmless.

### LT06 — `global { }` lifts assignments out of their scope [documented]

- "You don't need it in the main configuration file. But you
  might have difficulty setting a server wide configuration
  inside an included file from conditionals" — the documented
  fix is to wrap the server-wide assignments in `global { }`
  inside the included file [documented, Global context
  section, with the `server.modules += ("mod_fastcgi")` /
  `static-file.exclude-extensions += (...)` example].
- v1 semantics: assignments inside a `global { }` block are
  **unconditional (root-scope) assignments**, regardless of any
  conditional/include nesting around the block. Their
  precedence position is their position in the merged stream
  among root-scope assignments (LT15) [docs-inferred — the
  docs present `global` as a scope, not a hoist-to-top; a
  fixture pins stream position, flippable if the daemon in
  fact hoists]. A `global` block in the main file at root is a
  no-op wrapper. Missing the `global` wrapper is the classic
  failure this tool must not reproduce: treating those lines
  as conditional would attribute a server-wide module load to
  one vhost.

### LT07 — var. / env. are parse-time, sequential, and environment-dependent [documented]

- "Variables are expanded at startup when the configuration is
  parsed; variables are not expanded at runtime for each
  request" [documented, Using variables]. A `var.NAME`
  definition takes effect from its position in the merged
  stream; every later use — in a value, a condition's scope via
  an included file, an include path, an include_shell string —
  sees the value as defined *so far* [docs-inferred from
  parse-time expansion; a use before any definition is an
  unparseable-line finding (LT23), never an empty-string
  guess].
- Values compose with `+` over literals, `var.`, `env.`, and
  option references (`basedir + server.name` in the docs' own
  included-file example — note the docs write bare `basedir`
  and `PID` in included files for what the BNF calls
  `var.basedir` / `var.PID`; v1 accepts the bare form inside
  value expressions as an alias for the `var.` form and
  banners it, [hypothesized — the aliasing is in the docs'
  examples, never stated in the BNF]).
- Predefined: `var.PID` ("initialised to the pid of lighttpd
  before config is parsed" [documented]) and `var.CWD` (used
  as a base directory in the docs' examples [documented]).
  Both are daemon-runtime facts an off-box tool cannot know:
  a value depending on `var.PID` renders with a
  `<PID-unknown>` placeholder — the *decider* is still known,
  so the verdict stays EFFECTIVE with a finding (decider-known
  ≠ value-known, and the output must not blur them);
  `var.CWD` is resolved only from `--cwd DIR` (the directory
  the daemon was started in); without `--cwd`, a value
  depending on it is rendered `<CWD-unknown>` likewise.
- `env.NAME` reads the *daemon's startup environment*
  [documented BNF: "lighttpd.conf environment at startup"].
  The tool never reads its own environment (test-asserted —
  its environment is the wrong machine's). `env.NAME` values
  come only from repeatable `--env NAME=VALUE`; an `env.`
  reference with no `--env` for that name makes the containing
  expression `[env-unknown]`: if it feeds a value, render
  `<env:NAME-unknown>` with a finding; if it feeds an include
  path, the include is not followed and poisons per LT05's
  rule (a file the tool did not read could hold the decider);
  if it feeds a condition value, the condition is UNKNOWN
  (LT21).

### LT08 — Assignment operators are scope-local [documented]

- Within one scope (one `{ }` level in one condition block,
  or the root): `NAME = VALUE` assigns; `NAME += VALUE`
  merges/appends onto the value assigned *earlier in that same
  scope*; `NAME := VALUE` is replace/overwrite of the earlier
  value (since 1.4.46) [documented BNF + Merging section].
- **Duplicate `=` in the same scope:** the later line is the
  decider, the earlier is shadowed and listed as a finding
  [docs-inferred — a scope stores one value per key in the
  parsed form (`-p` prints one); the build pins last-wins with
  a fixture]. A `+=` with no earlier `=` in the same scope
  starts from empty for that scope (it does *not* reach into
  the parent scope — that is LT09).
- `var.NAME` definitions take the same three operators with
  the same scope-local reading [documented BNF]; a conditional
  block may define a `var.` used by a later include (the docs'
  host example does exactly this shape).

### LT09 — THE merging hazard: last matching condition wins, nothing merges across scopes [documented]

- "Options in different sections of the configuration **are
  not** merged dynamically at runtime. For a given option, the
  value of that option **in the last matching condition** is
  the value that is applied. Within the same lighttpd
  condition `{ ... }` and same nesting level of `{ ... }`, you
  can use `+=`, which is parsed at startup, but `+=` **does
  not apply** across different lighttpd conditions `{ ... }`
  or different nesting levels `{ ... }` within a condition."
  [documented, Conditional Configuration Merging — the
  section's emphasis is the docs' own.]
- Consequences, pinned as design rules:
  - A conditional assignment **replaces** the root (global)
    value whole for matching requests — arrays included. A
    root `url.access-deny = ( ".php" )` plus a conditional
    `url.access-deny = ( "" )` yields `( "" )` for matching
    requests, not `( ".php", "" )`. The Apache/nginx intuition
    (inherit-and-extend) is exactly wrong here.
  - A conditional `server.modules += ( "mod_x" )` does **not**
    extend the root module list for matching requests; per the
    docs, `+=` across conditions does not apply, so the
    conditional scope's value is its own `+=`-over-empty list
    [docs-inferred — this is the literal reading of the
    Merging section and a notorious real-world footgun; the
    fixture pins it and a live contradiction flips the
    reading, not the finding].
  - The tool's answer is therefore always *one* assignment's
    value (after LT07 expansion and LT08 same-scope merging),
    never a synthesized merge. Any output that merged values
    from two scopes would be a manufactured answer.

### LT10 — Conditional syntax: fields, operators, version gates [documented]

Fields (current docs): `$HTTP["host"]`, `$HTTP["url"]`
(path only, no host or query string), `$HTTP["querystring"]`,
`$HTTP["scheme"]` (`http|https`, since 1.4.19),
`$HTTP["request-method"]` (since 1.4.19), `$HTTP["remoteip"]`,
`$SERVER["socket"]`, `$REQUEST_HEADER["..."]` (arbitrary
header, name case-insensitive, since 1.4.46), and the legacy
header aliases `$HTTP["cookie"]`, `$HTTP["useragent"]`,
`$HTTP["language"]`, `$HTTP["referer"]` (subsumed by
`$REQUEST_HEADER[...]` since 1.4.46; v1 normalizes each alias
to its header and banners the alias). Field names inside
`$HTTP[...]` are matched as documented; note the docs use
`remoteip` and `querystring` (no hyphen) while other daemon
materials hyphenate — a hyphenated unknown field is
unparseable (LT23), not silently normalized.
Operators: `==` string equal, `!=` string not-equal, `=~`
PCRE match, `!~` PCRE not-match [documented], `=^` prefix and
`=$` suffix (both since 1.4.65) [documented]. The right-hand
side is a quoted string (literal or regex), possibly built by
`+`-concatenation (LT00/LT07).
Version gates v1 recognizes regardless of target version (it
does not know the daemon's version; the README states them):
bare `else { }` since 1.4.46; `:=` since 1.4.46;
`$REQUEST_HEADER` since 1.4.46; `=^`/`=$` since 1.4.65; the
literal `if` prefix and the `elif`/`elsif`/`elseif`/`else if`
spellings since 1.4.74; `$HTTP["remoteip"]` CIDR with IPv6
since 1.4.40 [all documented in the current docs]. "Some
versions do not support var. variables, appending with +=,
nested conditionals, or else blocks" at all [documented,
Troubleshooting] — configs written for those versions are
still parsed by v1's grammar; version mismatch is the
operator's deployment question, not a provenance question.

### LT11 — There are no AND/OR operators in 1.4 conditionals [documented + design rule]

- The 1.4 grammar has no boolean composition: AND is nesting
  (LT12), OR is repeating the block, choice is an else chain
  (LT13) [documented by the syntax's shape and the
  Limitations section; the lighttpd2 grammar's `and`/`or` is a
  different product and does not transfer]. A condition header
  containing `&&`, `||`, `and`, or `or` between comparisons is
  unparseable (LT23) — third-party blog examples showing
  `$HTTP["host"] == "a" || $HTTP["host"] == "b"` are not valid
  1.4 syntax and the tool must not quietly accept them.

### LT12 — Nesting is AND, and the nested scope is later [documented]

- "nesting: match only when parent match" [documented,
  Conditional Configuration syntax]. A nested condition is
  evaluated only under a matching parent; a FALSE parent makes
  the whole subtree FALSE without evaluating the child (the
  child's fields may not even be evaluatable for the request —
  the #2598 fix's "previous conditions must be evaluatable"
  concern, LT13).
- Precedence position (LT15): a scope's assignments sit at the
  position of their block in a depth-first document-order walk
  — parent block's own assignments before its nested blocks,
  in textual order. So when parent and nested child both match
  and both set the key, the child's assignment (later in the
  walk) is the decider [docs-inferred from last-matching-wins
  (LT09) plus nesting; pinned with a fixture].

### LT13 — else / elif chains: short-circuit, attached, never independent negations [documented + docs-inferred]

- Syntax: a condition block may be followed by
  `else <field> <op> <value> { }` (elif spellings since
  1.4.74, LT10) and/or a final bare `else { }` (since 1.4.46)
  at the same nesting level [documented].
- Semantics: the chain is one construct. "The first condition
  which evaluates true in any if-else condition chain
  short-circuits the chain, and any remaining conditions in
  the chain are marked false" (the #2598 fix description).
  An `else`-chain branch matches iff **all previous branches
  in its chain are FALSE** and its own test (if any) is TRUE.
  It is therefore *not* equivalent to a standalone block with
  a negated test: an `else $HTTP["host"] == "b"` branch also
  asserts the first branch's host test failed — load-bearing
  when the first branch's test is on a *different field*
  (`else` after a `$SERVER["socket"]` test, gated on a
  `$HTTP["host"]` test, means "socket did not match AND host
  is b").
- Three-valued reading (LT21): if a previous branch's test is
  UNKNOWN, every later branch in the chain is UNKNOWN (the
  daemon cannot mark them false), regardless of their own
  tests. A bare `else` after an UNKNOWN branch is UNKNOWN, not
  TRUE.
- **Attachment rule [design rule]:** an `else` attaches to the
  immediately preceding condition block at the same nesting
  level in the same file-scope of the merged stream, with only
  comments/blank lines between. An `else` with no attachable
  predecessor (start of a scope, after an assignment, after an
  include whose content does not end in a condition block) is
  an unparseable finding (LT23) poisoning its scope — silently
  treating it as a standalone "not-previous" block would
  manufacture semantics the grammar does not have. Whether an
  include boundary may sit between a block and its `else` is
  an open question (LT-open); v1 does not attach across one.

### LT14 — Identical conditions at the same scope are merged at parse time [documented]

- "At the same scope level (same level of { } nesting),
  identical condition blocks are merged during parsing at
  startup. Note that syntax errors may result from repeating
  a condition in if-else statements if the condition is
  already present at the same scope level (e.g. in other
  if-else statements)" [documented, Merging section].
- v1 models the merge: two textually separate
  `$HTTP["host"] == "a" { }` blocks at the same level are one
  scope whose assignments are taken in document order (LT08
  applies across the merged pair — a later `=` in the second
  textual block shadows the first, both cited). The decider
  citation names the assignment's own file:line and the
  finding notes the parse-time merge with the sibling block's
  header file:line.
- The same condition appearing both standalone and inside an
  else chain at one level is the documented error shape: v1
  raises a finding and treats the chain's copy per LT13 but
  flags the answer `[condition-merge-conflict]` [design rule
  — the daemon may refuse the config; the tool reports what
  the text says and names the risk, it does not adjudicate
  loadability beyond LT02/LT23 fatals].

### LT15 — Precedence: root is the base, matching scopes apply in document order [documented + docs-inferred]

The candidate order for a key, lowest to highest precedence:

1. Root-scope assignments (including `global { }` content,
   LT06), in merged-stream order — the fallback layer.
2. Matching conditional scopes, in depth-first document order
   (LT12), else-chain branches at their textual position
   (LT13).

The decider is the **last** candidate whose scope is TRUE for
the request (or the last root assignment). Root assignments
are the base *structurally*, not textually: a root assignment
textually **after** a conditional block does not override that
block for a matching request (it overrides earlier root
assignments only) [docs-inferred — this follows from "the
value in the last *matching condition* is applied" plus the
parsed form's separation of the global context from condition
contexts in `-p` output; it is the design's most consequential
inference and is pinned with a fixture: root-after-conditional
must NOT shadow the conditional for a matching request, and
MUST shadow an earlier root value for a non-matching one. A
live contradiction flips this rule first.]

### LT16 — $HTTP["host"]: authority, port suffix, case [documented + hypothesized]

- The field is the request's host (authority). "If you're not
  running on the default port, $HTTP["host"] will have the
  port appended to it, so regular expressions ending in `$`
  (without allowing for a port) won't match" [documented,
  Troubleshooting; the docs' fix is `(^|\.)example\.org
  (\:[0-9]*)?$`]. v1 evaluates the field as the `--host` value
  **as given** and raises a `[host-regex-port-trap]` finding
  for any host regex anchored at the end without a port
  allowance — the trap is common enough that naming it is
  part of the answer.
- Case: hostnames are case-insensitive and the daemon
  normalizes the authority; v1 compares `==`/`!=`/`=^`/`=$`
  on host case-insensitively and applies regexes to the
  lowercased host [hypothesized — the docs never state the
  normalization; lowercasing is the daemon's documented
  behavior for the authority in adjacent docs and the safe
  reading. A fixture pins it; a contradiction flips it and
  the finding trail names the flip].
- No `--host` supplied means the host field is *unspecified*,
  not empty: host tests are UNKNOWN (LT21). An explicitly
  empty host (`--host ''`, an HTTP/1.0 request with no Host)
  is the empty string and tests evaluate against it [design
  rule — the distinction between "field absent from the
  query" and "field empty in the request" is the whole
  three-valued game].

### LT17 — $HTTP["remoteip"]: CIDR only for ==/!=, and it is the peer, not the client [documented]

- "match on the remote IP address or a remote network `==` or
  `!=` CIDR mask (works with IPv6 since 1.4.40)" [documented].
  With `==`/`!=`, a value containing `/` is a network test
  (address-in-network, via `ipaddress` stdlib); without `/` it
  is a string test. With `=~`/`!~`/`=^`/`=$` the field is the
  textual peer address [docs-inferred]. A malformed CIDR is an
  unparseable finding (LT23).
- `--remoteip` is defined as *the peer address as the daemon
  sees it* (the TCP peer, or a unix socket's peer). It is not
  `X-Forwarded-For`: if the effective `server.modules` for the
  request includes `mod_extforward` (or a magnet script, LT25),
  the daemon may substitute a forwarded address before
  condition evaluation, and v1 banners `[peer-ip-may-be-
  rewritten]` on any answer whose decider chain contains a
  remoteip test [design rule — the substitution rules
  (trusted proxies, headers) are module configuration plus
  runtime headers, out of the static question's reach].

### LT18 — The remaining fields: url, querystring, scheme, method, headers [documented]

- `$HTTP["url"]` is the URL path only — "not including host
  or query-string" [documented]. It is the path as the daemon
  normalized it before condition evaluation; v1 evaluates the
  `--url` value as given and banners that daemon-side
  normalization (dot-segment / encoding cleanup under
  `server.http-parseopts`) is not reproduced [design rule —
  a `--url` containing `//`, `/./`, or %-escapes gets a
  `[url-normalization-not-modeled]` finding, not a silent
  rewrite].
- `$HTTP["querystring"]` is the part after `?` (empty string
  when there is no `?` — a supplied request always has a
  querystring value, possibly empty; only an *unsupplied*
  `--querystring` is UNKNOWN, LT16's rule) [docs-inferred].
- `$HTTP["scheme"]` is `http` or `https` [documented].
  `$HTTP["request-method"]` is the method token as sent
  [documented].
- `$REQUEST_HEADER["Name"]` matches the header's value; the
  header *name* is case-insensitive [documented]; a header
  absent from the supplied request is the empty string for
  `==`-family tests [docs-inferred — an absent header and an
  empty header are indistinguishable to the daemon's match].
  The query supplies at most one value per header
  (`--header` repeatable, last wins per name); a request with
  repeated headers is out of v1's query model and bannered if
  the user supplies duplicates.

### LT19 — Regexes are PCRE; Python `re` is a subset, never an approximation [documented + design rule]

- `=~` / `!~` are "perl style regular expression" matches
  [documented] — PCRE, unanchored (a search, not a full match)
  unless the pattern anchors itself. v1 translates patterns to
  Python `re` only for the common subset (literals, classes,
  alternation, quantifiers, groups, anchors, backreferences,
  `\d\w\s` and negations, non-greedy forms).
- Constructs with no faithful Python equivalent — lookbehind
  (fixed-width differences aside, any `(?<=` / `(?<!`),
  possessive quantifiers, `\z`, `\K`, conditional patterns,
  `(?<name>...)`, PCRE-only classes, recursion — make the
  condition `[regex-unknown]`: the test is UNKNOWN (LT21),
  never approximated, and the pattern is cited. An invalid
  regex (unbalanced, bad escape in both engines) is an
  unparseable finding (LT23): the daemon would fail to load
  it, so it poisons its scope rather than evaluating FALSE.

### LT20 — $SERVER["socket"]: a binding directive moonlighting as a condition [documented]

- "$SERVER["socket"] is valid in global scope; placing
  $SERVER["socket"] inside other conditions may have
  undesirable results (and would be rejected if not for
  historic (mis)use)" and a `==` test on it "also instructs
  lighttpd to bind to this socket" [documented]. The value is
  `ip:port` (ip optional → INADDR_ANY, or `[::]` when
  `server.use-ipv6 = "enable"` appears *inside this block*)
  or a unix-domain path [documented].
- v1: socket blocks are evaluated against `--socket` exactly
  as written (with the omitted-IP expansion applied for
  display). Socket selection is connection-level and happens
  before any `$HTTP` field exists, but for the *config
  selection* question it is just one more field — with one
  difference: if the config contains any socket scope that
  sets the queried key and no `--socket` was supplied, those
  scopes are UNKNOWN (LT21) — a very common real-world poison,
  since socket blocks are how :80/:443 splits are written.
  A socket block nested inside another condition raises the
  documented-undesirability finding, and is evaluated as
  written (nested = AND, LT12).

### LT21 — Three-valued evaluation and the Kleene core [design rule]

Every condition test evaluates TRUE, FALSE, or UNKNOWN for a
query. UNKNOWN sources: a field the query did not supply
(LT16/LT18/LT20), a `[regex-unknown]` pattern (LT19), an
`[env-unknown]` condition value (LT07), a previous else-chain
branch UNKNOWN (LT13), a parent UNKNOWN (child inherits
UNKNOWN, LT12).

For a key, walk candidates in LT15 precedence order:

- The last TRUE-scope assignment is the decider → verdict
  `EFFECTIVE`, unless an UNKNOWN-scope assignment for the key
  sits *after* it in precedence order → verdict `UNKNOWN`,
  blocker = that assignment's file:line (it might be the real
  decider and the tool cannot rule it out).
- UNKNOWN-scope assignments *before* the decider are absorbed
  with findings (a later known value wins regardless).
- No TRUE assignment and at least one UNKNOWN assignment →
  `UNKNOWN`. No assignments at all in any scope (after LT23
  poisoning checks) → `NOT-SET`. FALSE scopes never decide and
  never poison; they are listed in the chain so the reader can
  see what was ruled out.

### LT22 — Verdict vocabulary (exact)

- `EFFECTIVE` (exit 0): the key's effective value (LT07/LT08
  applied, LT24 rendering) and the decider's file:line, plus
  the scope chain that produced it.
- `NOT-SET` (exit 1): no assignment to the key applies to
  this request in the loaded tree. The daemon/module default
  is explicitly *not* stated (LT01).
- `UNKNOWN` (exit 1): poisoned — an UNKNOWN-scope decider
  candidate (LT21), an unfollowed include_shell / env-unknown
  include (LT05/LT07), a `global`/scope poison (LT23), or a
  runtime-dynamism override for this key (LT25); blocker
  cited in every case.
- There is no other output vocabulary for the verdict line;
  `--quiet` prints the verdict line only.

### LT23 — Unparseable lines poison the selected answer [design rule]

A line/block that matches no known shape — unknown condition
field, boolean operators in a header (LT11), orphan `else`
(LT13), malformed CIDR (LT17), invalid regex (LT19), use of an
undefined `var.` (LT07), a value expression referencing an
unknown name — is an unparseable finding. If it sits in a scope
that is TRUE or UNKNOWN for this request and could bear on the
queried key (any unparseable *assignment-shaped* line is
assumed to possibly assign any key; an unparseable *condition
header* poisons its whole subtree), the verdict is `UNKNOWN`
citing it. Unparseable lines in FALSE scopes, or plainly
non-assignment garbage outside any scope that could decide
this key, are warning findings only. Recognized-but-unevaluated
shapes (any `modulename.key = <any well-formed VALUE>`) are
parsed-or-skipped cleanly and never poison — the recognizer is
generous, the router strict. One broken vhost must not blind
the tool to the other forty.

### LT24 — Values are opaque, rendered as selected, captures not evaluated [design rule]

- The answer's value is the selected assignment's value after
  LT07 expansion and LT08 same-scope merging, rendered in
  config syntax (strings quoted, arrays parenthesized,
  key-lists with `=>`). The tool does not interpret the value
  per module: it does not resolve `alias.url` mappings, expand
  `fastcgi.server` arrays, or validate that a document-root
  exists.
- Values (in any scope) may contain per-request substitution
  tokens the daemon expands at runtime — `%0`–`%9` (from the
  last matching condition regex) and, inside rewrite/redirect
  arrays, `$0`–`$9` (from the rule's own regex) and
  `${url.*}`-style tokens. These are **not** config-selection
  and v1 does not evaluate them: a selected value containing
  them is rendered as written with a
  `[capture-substitution-not-evaluated]` finding, because the
  *assignment* is decided even though the final string is
  request-dependent. Decider-known, final-string-runtime —
  the same split as LT07's PID rule, stated once here for all
  token classes.

### LT25 — Runtime dynamism: bannered, and for document-root it poisons [documented + design rule]

Modules can decide per-request what no condition block says:

- `mod_simple_vhost`: document-root is
  `simple-vhost.server-root + host + simple-vhost.document-root`
  resolved against directories that may be created or removed
  *without a daemon restart* (filesystem state, not config).
- `mod_evhost`: document-root from `evhost.path-pattern`
  substitutions (`%0` = host+tld, `%1`…`%4` = host parts).
- `mod_vhostdb` / `mod_mysql_vhost`: document-root from a
  database lookup.
- `mod_magnet`: Lua scripts run per request and can set
  physical paths and response behavior arbitrarily.
- `mod_extforward`: rewrites the peer address (LT17's banner).

v1 rule: these modules are detected from the *effective-for-
this-request* `server.modules` value whenever that value is
itself EFFECTIVE (and from any root-scope modules assignment
otherwise, bannered as approximate). For the key
`server.document-root`, the presence of `mod_simple_vhost`,
`mod_evhost`, `mod_vhostdb`, `mod_mysql_vhost`, or
`mod_magnet` in that list makes the verdict `UNKNOWN` with
the modules line as blocker, even when a conditional
assignment exists — the module, not the assignment, is the
decider at runtime. For every other key, the presence of any
of these modules is a coverage banner only.

### LT26 — Safety: nothing in the config is ever executed or dumped [family rule]

lighttpd configs contain shell commands (LT05), script paths
(fastcgi/cgi backends), and secrets (auth backends, database
credentials for vhostdb, SSL key *paths*). v1: pure text
parsing; no subprocess, no network, no writes, no environment
reads (LT07) — test-asserted. Coverage and inventory modes
list keys, scopes, and file:lines, never a dump of all values;
the only value printed is the queried key's selected value
(that is the question asked) and values in findings are
truncated to the assignment's own line. `include_shell`
command strings are printed verbatim in the inventory
(the operator wrote them and needs to see what was *not*
run), never executed.

## CLI, exits, and output contract

```
lighttpdwho KEY [--host H] [--url P] [--scheme S] [--method M]
                [--querystring Q] [--remoteip IP]
                [--socket SOCK] [--header 'Name: value']...
                [--env K=V]... [--cwd DIR] [--conf FILE]...
lighttpdwho --list-conditions [--conf FILE]...
lighttpdwho --list-keys [--conf FILE]...
```

- One positional query: a top-level key (LT01). Request fields
  are optional individually, but a field the config *tests*
  and the query omits is UNKNOWN (LT21) — the tool never
  defaults a field the operator did not supply, with two
  exceptions: `--scheme` is never defaulted either (an
  omitted scheme is UNKNOWN where tested); there are no
  exceptions. (Earlier who-tools defaulted a port or a
  scheme; this one does not — an invented field value is a
  manufactured answer.)
- `--list-conditions`: every conditional block in the merged
  stream, in document order, with header file:line, field/op/
  value, nesting path (including else-chain position, LT13),
  merged-sibling note (LT14), and the keys assigned inside.
  Exit 0 with ≥1 block, exit 1 with none.
- `--list-keys`: every assigned key with its assignment count
  by scope kind (root / each distinct condition), first and
  last file:line. Exit 0 with ≥1 key, exit 1 with none.
- Exit 0: verdict `EFFECTIVE`, or an inventory mode with ≥1
  item. Exit 1: `NOT-SET`, `UNKNOWN`, or an inventory mode
  with nothing listed. Exit 2: usage error, missing config,
  missing literal include (LT02), include cycle (LT02), or a
  malformed query (bad `--remoteip`, bad `--header` shape,
  key not of `modulename.key` shape).
- Output order (text): verdict line; decider citation
  (file:line of the assignment, plus its scope's header
  file:line chain); the selected value; the candidate chain
  (every assignment to the key in precedence order with its
  scope verdict TRUE/FALSE/UNKNOWN and file:line — the
  auditable form of LT15/LT21); findings; unmodeled inventory
  (include_shell lines LT05, env-unknown references LT07,
  regex-unknown patterns LT19); coverage (LT27).
  `--json` renders the same structure machine-readably.
- Read-only by construction (LT26).

### LT27 — Coverage on every run [design rule]

Output always lists: files read (byte/line counts, each
include directive with its resolved path and expansion kind —
literal/glob/empty), include_shell directives (count +
file:lines), scopes defined (count by kind, headers cited),
keys assigned (count), gated/UNKNOWN-scope assignments for
this key, `env.`/`var.PID`/`var.CWD` dependencies, and
skipped/unparseable lines with counts. A verdict over a
partially read config is never presented as complete.

## Out of scope (bannered, never silently modeled)

- **Request handling** — rewriting, redirecting, backend
  selection, access decisions (LT01).
- **Module-internal config use** — how a module merges or
  interprets the selected value beyond LT09's selection rule
  (LT24), except the LT25 document-root override.
- **Runtime vhosting** — simple_vhost/evhost/vhostdb/magnet
  results (LT25); **filesystem state** — whether a
  document-root or backend socket exists.
- **include_shell output** (LT05) and **daemon environment**
  beyond `--env` (LT07).
- **URL normalization** before url matching (LT18) and
  **forwarded-peer substitution** (LT17).
- **The running daemon's state** — loaded-vs-disk honesty:
  every verdict is labeled on-disk config selection;
  `lighttpd -p` on the host is the live parsed form, and
  reaching it requires executing the config's shell
  fragments (LT05), which is precisely why this tool exists
  as a static reader.

## Not a validator (deliberate divergence, documented)

Real lighttpd refuses to start on any syntax error; lighttpdwho
degrades: broken blocks it was not asked about are warning
findings (LT23), and only defects that can change *this key's*
answer poison the verdict. The README must say this in one
paragraph, and must say `lighttpd -t` remains the validation
path. The exceptions are load failures — missing literal
include (LT02) and include cycles — which are fatal (exit 2)
because the daemon would not load the config at all and there
is no tree to answer over.

## Hazards reviewed (why this design is safe to build)

1. **Cross-scope merging is the catastrophic intuition
   (LT09/LT15).** Every other server in the who-family
   (Apache, nginx) inherits-and-merges; lighttpd replaces,
   per-option, from the last matching condition, and `+=`
   refuses to cross a scope boundary. A tool built on merge
   intuition would report module lists and access-deny arrays
   that no request ever sees — confidently, plausibly, and
   wrong. Hence LT09 as a headline, LT08/LT15's candidate
   chain in every answer, and fixtures that would fail loudly
   under a merging implementation.
2. **include_shell is execution wearing a config directive
   (LT05).** It is also the stock Debian idiom, so "just run
   it like the daemon does" is the path of least resistance —
   and would make a read-only provenance tool execute
   arbitrary shell from the file it was asked to *inspect*,
   with the operator's credentials and environment. Never
   executed, poisoned positionally, inventoried verbatim.
   The same argument kills `lighttpd -p` as a live oracle.
3. **Relative includes resolve against the main file, not the
   including file (LT03).** The keepalived rule is the exact
   opposite, so a builder porting intuition (or code) across
   the family will load `vhosts/conf.d/...` files that the
   daemon never reads and miss the ones it does. The finding
   on cross-directory relative includes exists so the
   resolution is visible in the answer, not buried in the
   loader.
4. **else is a chain position, not a negation (LT13).** Read
   as an independent `!=` test, an else branch's assignments
   get credited to requests that actually matched the *first*
   branch — the classic "the else vhost served my production
   host" mystery, manufactured by the tool. The short-circuit
   + previous-branch-UNKNOWN rules are the fix, and separating
   `else` from its chain is treated as a parse error, not a
   fallback reading.
5. **The `global {}` escape inverts scope silently (LT06).**
   Assignments that look conditional (inside an include,
   inside a vhost block) are in fact server-wide. Missing it
   attributes global module loads to a single vhost; the
   inverse error (applying it where the wrapper is absent)
   is prevented by making `global` the *only* escape the
   loader honors.
6. **Host-with-port regex trap (LT16).** `$HTTP["host"]
   =~ "(^|\.)example\.org$"` silently stops matching on any
   non-default port. The docs themselves call this out as
   the top troubleshooting item; a tool that evaluated it
   without naming the trap would reproduce the operator's
   confusion instead of explaining it.
7. **PCRE is not Python `re` (LT19).** Approximating an
   unsupported pattern would turn UNKNOWN answers into
   wrong TRUE/FALSE answers on exactly the gnarly patterns
   real configs use for bot/host filtering. The subset
   boundary is explicit and everything past it is
   `[regex-unknown]`.
8. **Runtime vhost modules override the file (LT25).** With
   simple_vhost loaded, directories appearing on disk change
   the answer with no config change at all. Answering
   `server.document-root` from condition blocks while
   simple_vhost is loaded would be the tool's most confident
   wrong answer; hence the targeted UNKNOWN, scoped to the
   one key those modules own.

## Test plan (hermetic fixture configs; stdlib-only runner)

~68 tests, plain `python3` (no pytest — the aptpinswho lesson):

- **BG1 (core selection, LT01/LT15/LT22):** root-only key
  (EFFECTIVE, root decider); conditional override for a
  matching host; same config, non-matching host → root value;
  root assignment *after* the conditional block does not
  shadow it for a matching request and does shadow an earlier
  root value for a non-matching one (LT15 fixture); NOT-SET
  for an unassigned key (exit 1); NOT-SET with an empty glob
  listed as `[possibly-missing]` (LT04); a key assigned only
  in a FALSE scope → NOT-SET with the chain shown; `--quiet`
  and exit-code matrix.
- **BG2 (merging, LT08/LT09/LT14):** `+=` within one scope
  appends; `+=` in a conditional does **not** extend the root
  array (conditional value stands alone — LT09 fixture);
  conditional `=` replaces a root array whole; `:=` replaces
  an earlier same-scope value; duplicate `=` in one scope →
  later decider, earlier cited as shadowed; identical
  condition blocks at one level merged (assignments from both
  textual blocks considered in order, merge finding shown);
  nested `+=` does not reach the parent scope's value.
- **BG3 (fields & operators, LT10/LT16/LT17/LT18/LT20):**
  each operator (`==`, `!=`, `=~`, `!~`, `=^`, `=$`) true and
  false; remoteip CIDR `==` in/out of network + IPv6 CIDR +
  malformed CIDR poison; host regex port trap finding;
  host `==` case-insensitivity; querystring supplied-empty vs
  unsupplied; `$REQUEST_HEADER` name case-insensitivity +
  legacy `$HTTP["useragent"]` alias normalization; missing
  header = empty string; socket `==` match/mismatch, omitted-
  IP expansion, socket block with no `--socket` → UNKNOWN
  blocker.
- **BG4 (nesting & else, LT11/LT12/LT13):** nested AND
  (parent true/child true, parent true/child false, parent
  false/child not evaluated); nested child decider over
  parent; else branch taken only when the first is false;
  elif chain: first true short-circuits later branches;
  else-after-different-field (socket-then-host chain, LT13);
  previous branch UNKNOWN → bare else UNKNOWN; orphan else →
  poison; a header with `||` → unparseable poison (LT11);
  `if`-prefixed and `elif`-spelled headers parse (LT10).
- **BG5 (three-valued core, LT21):** unsupplied `--host` with
  a host-scope decider candidate after a root value →
  UNKNOWN citing it; UNKNOWN-scope assignment *before* a
  later TRUE decider → EFFECTIVE with the absorbed finding;
  parent UNKNOWN → child UNKNOWN; no TRUE + one UNKNOWN →
  UNKNOWN; chain listing shows TRUE/FALSE/UNKNOWN per
  candidate.
- **BG6 (includes, LT02/LT03/LT04/LT06):** include at root;
  include inside a host block contributes conditional
  assignments; nested include's *relative* path resolved
  against the main file's directory (LT03 fixture — the
  including file's own directory contains a decoy file that
  must NOT be read); glob include sorted order deciding a
  same-scope duplicate; glob no-match warning; literal
  missing include → exit 2; include cycle → exit 2;
  `global { }` inside a conditionally included file lifts
  its assignments to root (LT06 fixture) while the file's
  non-global assignments stay conditional; multiple `--conf`
  concatenation with per-root relative bases.
- **BG7 (var/env/shell, LT05/LT07):** var defined then used
  in a value and in an include path; var redefinition —
  later uses see the later value, earlier assignments keep
  theirs; use-before-definition poison; `+` concatenation of
  literal + var + option reference; `var.PID` value →
  EFFECTIVE with `<PID-unknown>` placeholder + finding;
  `var.CWD` with and without `--cwd`; `env.` from `--env`
  only (a value present in the *tool's* environment but not
  passed via `--env` must NOT leak — harness sets a trap
  variable); env-unknown in a value / include path /
  condition value (three poison shapes); include_shell at
  root with no later decider → UNKNOWN blocker;
  include_shell *before* a later unconditional decider →
  absorbed with finding; include_shell in a FALSE scope →
  harmless; include_shell marker-file test: the command
  names a path in the fixture tmpdir and the test asserts
  the marker was never created (never-executes).
- **BG8 (regex, LT19/LT24):** common-subset patterns
  (anchors, classes, alternation, captures) evaluate;
  unanchored search semantics (`=~ "download"` matches
  mid-path); lookbehind pattern → `[regex-unknown]` →
  UNKNOWN verdict, never a guess; possessive quantifier →
  regex-unknown; invalid pattern → scope poison; selected
  value containing `%1`/`$1` tokens rendered verbatim with
  the `[capture-substitution-not-evaluated]` finding.
- **BG9 (dynamism, coverage, safety; LT18/LT20/LT25/LT26/
  LT27):** `mod_simple_vhost` in modules + document-root
  query → UNKNOWN with the modules blocker; same config,
  a non-document-root key → EFFECTIVE with banner;
  `mod_extforward` in modules + remoteip decider chain →
  `[peer-ip-may-be-rewritten]` banner; url with `/../` →
  normalization finding, value still evaluated as given;
  `--list-conditions` (nesting paths, else positions, merge
  notes) and `--list-keys` output + empty-tree exits;
  `--json` fidelity vs text verdicts; coverage completeness
  (every fixture asserts all files/scopes/keys are named);
  no-subprocess/no-network/no-write/no-environment harness
  (family standard) with payloads in comments, include_shell
  lines, and script-path values.

Dogfood: doccover + clicheck clean before the v1 commit, per
bench convention. README carries a Limitations section naming
LT05/LT09/LT15/LT19/LT25 and the Out-of-scope list explicitly,
plus a pre-publish checklist.

## Build order

1. Tokenizer + loader (LT00 comments/strings/operators,
   LT02 include chain, LT03 main-dir resolution, LT04 globs,
   LT06 global lifting, LT07 var/env stream, LT23
   recognizer).
2. Scope tree (LT12 nesting, LT13 else attachment/chains,
   LT14 identical-condition merge) + condition evaluator
   (LT10 fields, LT16–LT20 field semantics, LT19 regex
   subset, LT21 three-valued logic).
3. Selection engine (LT15 candidate order, LT08 same-scope
   operators, LT09 no-cross-scope-merge) + LT25 dynamism
   gate + renderers (text/JSON) + coverage (LT27) +
   inventory modes.
4. Dogfood: doccover + clicheck --strict; bench-audit map
   extension; prepublish-check clean; README + CHANGELOG.

## Open questions / flippable hypotheses

1. **Root-vs-conditional precedence is positional or
   structural (LT15).** v1 pins structural (root is always
   the base layer; a later root line never shadows a matching
   conditional). If a live `-p` + request test (on a config
   without include_shell) shows the daemon applying textual
   order across the root/condition boundary, the candidate
   order becomes pure document order — the chain output
   already displays both orders' candidates, so the flip is
   mechanical.
2. **Conditional `+=` starting value (LT09).** v1 pins the
   literal Merging-section reading (`+=` over empty in the
   conditional scope). The long-standing maintainer comment
   (bug #2597) that directives in each condition are treated
   "independent from directives in other conditions" supports
   it, but if a live test shows a conditional `+=` extending
   the *root* list at runtime for some value types (arrays
   vs strings), LT09 splits by type and the fixtures flip
   per type.
3. **Glob order and glob flavor (LT04).** Byte-wise sorted is
   pinned; the C library's glob under a non-C locale, and
   its handling of `?`/`[...]`, may diverge from Python's.
   Order only matters for same-scope duplicates across
   globbed files.
4. **Glob no-match (LT04).** v1: empty + warning. If the
   daemon in fact fails to load on a zero-match glob, this
   becomes fatal exit 2 like a literal miss.
5. **Else attachment across an include boundary (LT13).**
   v1 does not attach. If the merged-stream grammar the
   daemon implements attaches an `else` to a condition block
   that ended an included file, the loader must track
   last-block across file boundaries.
6. **`global { }` position (LT06).** v1: stream position
   among root assignments. If `global` content is in fact
   hoisted (e.g. applied before all root assignments), only
   duplicate-root-key fixtures change.
7. **Host case normalization (LT16).** Lowercasing is
   hypothesized from adjacent daemon behavior, not from the
   config docs. A source read of the condition evaluation
   for `host` settles it; regex-on-host is the affected
   surface.
8. **Bare-name var alias in included files (LT07).** The
   docs' examples write `basedir` / `PID` bare. If the real
   grammar requires `var.` everywhere and the examples are
   shorthand, the alias becomes an unparseable finding
   instead of a bannered acceptance.
9. **Identical-condition merge vs else chains (LT14).** The
   docs warn of syntax errors when a condition repeats inside
   if-else at one level. v1 reports and proceeds; if the
   daemon's refusal is total, that shape should become exit 2
   rather than `[condition-merge-conflict]`.

## Sources (read 2026-11-09)

- Docs_Configuration — lighttpd (redmine, current):
  https://redmine.lighttpd.net/projects/1/wiki/docs_configuration
  (BNF: `=`, `+=`, `:=` since 1.4.46, `var.`, `env.`, include,
  include_shell; conditional fields/operators incl. `=^`/`=$`
  since 1.4.65, `$REQUEST_HEADER` since 1.4.46, bare else
  since 1.4.46, `if`/`elif` spellings since 1.4.74;
  Conditional Configuration Merging: not merged at runtime,
  last matching condition, `+=` does not cross conditions or
  nesting levels, identical blocks merged at same scope;
  Using variables: parse-time expansion, var.PID, var.CWD;
  Limitations; Global context with the included-file example;
  Troubleshooting: host port suffix)
- lighttpd(8) — Debian manpages (experimental):
  https://manpages.debian.org/experimental/lighttpd/lighttpd.8.en.html
  (`-f` configfile and default /etc/lighttpd/lighttpd.conf,
  `-p` print parsed configuration in internal form, `-t`
  test syntax, `-tt` test + load modules)
- lighttpd forum / redmine activity, gstrauss (2022-12):
  include and include_shell relative paths resolve against
  the directory of the main configuration file (via
  https://redmine.lighttpd.net/activity?from=2022-12-22&show_messages=1&user_id=10519)
- lighttpd redmine activity (2016-05): "[config] support
  include file glob (fixes #1221)"; (2016-02) revision for
  #2598, "[core] never evaluate else branches until the
  previous branches are already (ready)": first true branch
  short-circuits the if-else chain
  (via https://redmine.lighttpd.net/activity?from=2016-02-25&user_id=10519)

## Verdict

**BUILD APPROVED.** The gap holds in full: `lighttpd -t`
validates without adjudicating, and `lighttpd -p` — the
nearest native holder — prints a flattened, provenance-free
parsed form whose production requires executing the config's
own `include_shell` fragments, so it cannot serve as a safe
static oracle. The semantics are pinnable from the current
docs to the precision this tool needs — last-matching-wins
with no cross-scope merging (LT09), parse-time merged
identical scopes (LT14), nesting-as-AND (LT12), short-circuit
else chains (LT13), main-directory relative includes (LT03),
and the `global {}` scope escape (LT06) — with the genuinely
uncertain points (root/conditional precedence shape,
conditional `+=` starting value, glob flavor, host case
normalization) isolated as flippable hypotheses whose fixtures
pin the chosen reading. The three-valued walk (LT21) plus the
positional include_shell poison (LT05) and the runtime-vhost
UNKNOWN for `server.document-root` (LT25) keep the tool honest
about what a static file cannot decide. Build in the order
above; the v1 commit gate is the BG1–BG9 suite green plus
doccover/clicheck clean. **Publishing is NOT covered by this
verdict** — lighttpdwho was not among the campaign's three
pre-approved tools; it follows the normal per-project approval
path when built.
