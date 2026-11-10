"""Tests for lighttpdwho. Hermetic fixture-tree tests (BG1-BG9);
stdlib-only runner, plain `python3 test_lighttpdwho.py` (no pytest
-- the aptpinswho lesson). No lighttpd binary exists on this box,
so there is no live-agreement test to skip-guard against; fixture
trees are the only oracle, exactly as the manual text is the only
authority."""

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "lighttpdwho")
_mod = importlib.machinery.SourceFileLoader("lighttpdwho_mod", TOOL)
lighttpdwho = _mod.load_module()

TRAP_ENV = "LIGHTTPDWHO_TRAP_VAR"


def run_cli(args, cwd=None, env=None):
    proc = subprocess.run([sys.executable, TOOL] + args,
                          capture_output=True, text=True, cwd=cwd,
                          env=env)
    return proc.returncode, proc.stdout, proc.stderr


class TmpTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lighttpdwho-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def conf(self, text, name="lighttpd.conf"):
        return self.write(name, text)

    def query(self, key, conf_path, extra=None, conf_args=None):
        args = [key]
        if conf_args is not None:
            args += conf_args
        else:
            args += ["--conf", conf_path]
        if extra:
            args += extra
        return run_cli(args)

    def query_json(self, key, conf_path, extra=None, conf_args=None):
        rc, out, err = self.query(key, conf_path,
                                  (extra or []) + ["--json"], conf_args)
        try:
            data = json.loads(out)
        except ValueError:
            self.fail("not JSON (rc=%d, err=%r): %r" % (rc, err, out))
        return rc, data, err

    def findings(self, data):
        return [f["tag"] + ": " + f["message"]
                for f in data.get("findings", [])]

    def has_finding(self, data, needle):
        return any(needle in f for f in self.findings(data))


# ------------------------------------------------------------------- BG1

class BG1CoreSelection(TmpTree):
    def test_root_only_key_is_effective(self):
        cfg = self.conf('server.document-root = "/var/www"\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/www"')
        self.assertEqual(data["decider"]["where"], cfg + ":1")
        self.assertEqual(data["decider"]["scope"], "root")

    def test_conditional_override_for_matching_host(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/a"')
        self.assertEqual(data["decider"]["where"], cfg + ":3")

    def test_nonmatching_host_falls_back_to_root(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/www"')
        self.assertEqual(data["decider"]["where"], cfg + ":1")

    def test_root_after_conditional_does_not_shadow_it(self):
        # LT15 fixture: root is the base layer structurally, not
        # textually.
        cfg = self.conf(
            'server.document-root = "/var/early"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n'
            'server.document-root = "/var/late"\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"/var/a"')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["value"], '"/var/late"')
        self.assertEqual(data["decider"]["where"], cfg + ":5")

    def test_not_set_for_unassigned_key(self):
        cfg = self.conf('server.document-root = "/var/www"\n')
        rc, data, _ = self.query_json("ssl.engine", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "NOT-SET")
        self.assertIsNone(data["decider"])
        self.assertIsNone(data["value"])

    def test_not_set_with_empty_glob_listed_as_possibly_missing(self):
        cfg = self.conf(
            'include "%s/conf.d/*.conf"\n'
            'server.port = 80\n' % self.tmp)
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["verdict"], "NOT-SET")
        self.assertEqual(len(data["possibly_missing_globs"]), 1)
        rc, out, _ = self.query("server.document-root", cfg,
                                ["--host", "a.example"])
        self.assertIn("[possibly-missing]", out)

    def test_key_only_in_false_scope_is_not_set(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["verdict"], "NOT-SET")
        self.assertEqual(len(data["candidates"]), 1)
        self.assertEqual(data["candidates"][0]["verdict"], "FALSE")

    def test_quiet_prints_verdict_line_only(self):
        cfg = self.conf('server.document-root = "/var/www"\n')
        rc, out, _ = self.query("server.document-root", cfg,
                                ["--host", "a.example", "--quiet"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "EFFECTIVE\n")

    def test_exit_code_matrix(self):
        cfg = self.conf('server.port = 80\n')
        rc, _, err = self.query("nodot", cfg)
        self.assertEqual(rc, 2)
        rc, _, err = self.query("server.port", cfg,
                                ["--remoteip", "not-an-ip"])
        self.assertEqual(rc, 2)
        rc, _, err = self.query("server.port", cfg,
                                ["--header", "no-colon-here"])
        self.assertEqual(rc, 2)
        rc, _, err = self.query("server.port", cfg,
                                ["--env", "NOEQUALS"])
        self.assertEqual(rc, 2)
        rc, _, err = run_cli(["server.port", "--conf",
                              os.path.join(self.tmp, "nope.conf")])
        self.assertEqual(rc, 2)
        rc, _, err = run_cli(["server.port"])
        self.assertEqual(rc, 2)  # no --conf and no /etc default


# ------------------------------------------------------------------- BG2

class BG2Merging(TmpTree):
    def test_plus_equals_appends_within_one_scope(self):
        cfg = self.conf(
            'server.modules = ( "mod_a" )\n'
            'server.modules += ( "mod_b" )\n')
        rc, data, _ = self.query_json("server.modules", cfg)
        self.assertEqual(data["value"], '( "mod_a", "mod_b" )')

    def test_plus_equals_in_conditional_does_not_extend_root(self):
        # LT09 fixture: += does not cross a scope boundary.
        cfg = self.conf(
            'server.modules = ( "mod_a" )\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.modules += ( "mod_b" )\n'
            '}\n')
        rc, data, _ = self.query_json("server.modules", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '( "mod_b" )')
        rc, data, _ = self.query_json("server.modules", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["value"], '( "mod_a" )')

    def test_conditional_equals_replaces_root_array_whole(self):
        cfg = self.conf(
            'url.access-deny = ( ".php" )\n'
            '$HTTP["host"] == "a.example" {\n'
            '  url.access-deny = ( "" )\n'
            '}\n')
        rc, data, _ = self.query_json("url.access-deny", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '( "" )')

    def test_colon_equals_replaces_earlier_same_scope_value(self):
        cfg = self.conf(
            'server.port = 80\n'
            'server.port := 8080\n')
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(data["value"], "8080")
        self.assertEqual(data["decider"]["where"], cfg + ":2")

    def test_duplicate_equals_later_decider_earlier_shadowed(self):
        cfg = self.conf(
            'server.port = 80\n'
            'server.port = 81\n')
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(data["value"], "81")
        self.assertEqual(data["decider"]["where"], cfg + ":2")
        self.assertTrue(self.has_finding(data, "LT08"))
        self.assertTrue(self.has_finding(data, "shadowed"))

    def test_identical_conditions_merged_at_parse_time(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a1"\n'
            '}\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a2"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"/var/a2"')
        self.assertEqual(data["decider"]["where"], cfg + ":5")
        self.assertTrue(self.has_finding(data, "LT14"))
        self.assertTrue(self.has_finding(data, "merged"))

    def test_nested_plus_equals_does_not_reach_parent_scope(self):
        cfg = self.conf(
            'server.modules = ( "mod_a" )\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.modules = ( "mod_h" )\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.modules += ( "mod_n" )\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.modules", cfg,
            ["--host", "a.example", "--url", "/x"])
        self.assertEqual(data["value"], '( "mod_n" )')
        rc, data, _ = self.query_json(
            "server.modules", cfg,
            ["--host", "a.example", "--url", "/y"])
        self.assertEqual(data["value"], '( "mod_h" )')


# ------------------------------------------------------------------- BG3

class BG3FieldsAndOperators(TmpTree):
    def test_eq_and_ne(self):
        cfg = self.conf(
            '$HTTP["url"] == "/a" {\n'
            '  server.name = "eq"\n'
            '}\n'
            '$HTTP["url"] != "/a" {\n'
            '  server.name = "ne"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/a"])
        self.assertEqual(data["value"], '"eq"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/b"])
        self.assertEqual(data["value"], '"ne"')

    def test_regex_match_and_not_match(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "^/admin" {\n'
            '  server.name = "admin"\n'
            '}\n'
            '$HTTP["url"] !~ "^/admin" {\n'
            '  server.name = "other"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/admin/users"])
        self.assertEqual(data["value"], '"admin"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/public"])
        self.assertEqual(data["value"], '"other"')

    def test_prefix_and_suffix_operators(self):
        cfg = self.conf(
            '$HTTP["url"] =^ "/static" {\n'
            '  server.name = "prefix"\n'
            '}\n'
            '$HTTP["url"] =$ ".php" {\n'
            '  server.name = "suffix"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/static/x.css"])
        self.assertEqual(data["value"], '"prefix"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/app/index.php"])
        self.assertEqual(data["value"], '"suffix"')

    def test_remoteip_cidr_in_and_out(self):
        cfg = self.conf(
            '$HTTP["remoteip"] == "10.0.0.0/8" {\n'
            '  server.name = "internal"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "10.1.2.3"])
        self.assertEqual(data["value"], '"internal"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "192.168.1.1"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_remoteip_cidr_not_equal(self):
        cfg = self.conf(
            '$HTTP["remoteip"] != "10.0.0.0/8" {\n'
            '  server.name = "external"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "192.168.1.1"])
        self.assertEqual(data["value"], '"external"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "10.9.9.9"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_remoteip_ipv6_cidr(self):
        cfg = self.conf(
            '$HTTP["remoteip"] == "2001:db8::/32" {\n'
            '  server.name = "v6"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "2001:db8::1"])
        self.assertEqual(data["value"], '"v6"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "2001:db9::1"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_malformed_cidr_poisons_scope(self):
        cfg = self.conf(
            '$HTTP["remoteip"] == "10.0.0.0/33" {\n'
            '  server.name = "bad"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "10.1.2.3"])
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT23"))

    def test_host_regex_port_trap_finding(self):
        cfg = self.conf(
            '$HTTP["host"] =~ "(^|\\\\.)example\\\\.org$" {\n'
            '  server.name = "trap"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "www.example.org"])
        self.assertEqual(data["value"], '"trap"')
        self.assertTrue(self.has_finding(data, "host-regex-port-trap"))

    def test_host_eq_is_case_insensitive(self):
        cfg = self.conf(
            '$HTTP["host"] == "A.Example" {\n'
            '  server.name = "ci"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"ci"')

    def test_querystring_supplied_empty_vs_unsupplied(self):
        cfg = self.conf(
            '$HTTP["querystring"] == "" {\n'
            '  server.name = "noqs"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--querystring", ""])
        self.assertEqual(data["value"], '"noqs"')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(data["verdict"], "UNKNOWN")

    def test_request_header_name_case_insensitive(self):
        cfg = self.conf(
            '$REQUEST_HEADER["X-Test"] == "yes" {\n'
            '  server.name = "hdr"\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.name", cfg, ["--header", "x-test: yes"])
        self.assertEqual(data["value"], '"hdr"')

    def test_legacy_useragent_alias_normalized(self):
        cfg = self.conf(
            '$HTTP["useragent"] =~ "bot" {\n'
            '  server.name = "bot"\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.name", cfg,
            ["--header", "User-Agent: googlebot/1.0"])
        self.assertEqual(data["value"], '"bot"')
        self.assertTrue(self.has_finding(data, "LT10"))

    def test_missing_header_is_empty_string(self):
        cfg = self.conf(
            '$REQUEST_HEADER["X-Nope"] == "" {\n'
            '  server.name = "absent"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(data["value"], '"absent"')

    def test_socket_match_and_mismatch(self):
        cfg = self.conf(
            '$SERVER["socket"] == "0.0.0.0:80" {\n'
            '  server.name = "port80"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--socket", "0.0.0.0:80"])
        self.assertEqual(data["value"], '"port80"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--socket", "0.0.0.0:443"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_socket_omitted_ip_expansion(self):
        cfg = self.conf(
            '$SERVER["socket"] == ":80" {\n'
            '  server.name = "any80"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--socket", "0.0.0.0:80"])
        self.assertEqual(data["value"], '"any80"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--socket", ":80"])
        self.assertEqual(data["value"], '"any80"')

    def test_socket_block_with_no_socket_arg_is_unknown(self):
        cfg = self.conf(
            '$SERVER["socket"] == ":443" {\n'
            '  server.name = "tls"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(data["blocker"]["line"], 2)

# ------------------------------------------------------------------- BG4

class BG4NestingAndElse(TmpTree):
    def test_nested_and_both_true_child_decides(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.document-root = "/var/ax"\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.document-root", cfg,
            ["--host", "a.example", "--url", "/x"])
        self.assertEqual(data["value"], '"/var/ax"')
        self.assertEqual(data["decider"]["where"], cfg + ":4")

    def test_nested_parent_true_child_false_parent_decides(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.document-root = "/var/ax"\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.document-root", cfg,
            ["--host", "a.example", "--url", "/y"])
        self.assertEqual(data["value"], '"/var/a"')

    def test_nested_parent_false_child_not_evaluated(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.document-root = "/var/ax"\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.document-root", cfg,
            ["--host", "c.example", "--url", "/x"])
        self.assertEqual(data["value"], '"/var/www"')
        self.assertEqual(data["decider"]["where"], cfg + ":1")

    def test_else_branch_taken_only_when_first_is_false(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '} else {\n'
            '  server.document-root = "/var/other"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"/var/a"')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "b.example"])
        self.assertEqual(data["value"], '"/var/other"')

    def test_elif_chain_first_true_short_circuits(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '} elif $HTTP["host"] == "b.example" {\n'
            '  server.name = "b"\n'
            '} else {\n'
            '  server.name = "other"\n'
            '}\n')
        for host, want in (("a.example", '"a"'), ("b.example", '"b"'),
                           ("c.example", '"other"')):
            rc, data, _ = self.query_json("server.name", cfg,
                                          ["--host", host])
            self.assertEqual(data["value"], want, host)

    def test_else_after_different_field(self):
        # LT13: the else branch also asserts the socket test failed.
        cfg = self.conf(
            '$SERVER["socket"] == ":80" {\n'
            '  server.name = "port80"\n'
            '} else $HTTP["host"] == "b.example" {\n'
            '  server.name = "hostb"\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.name", cfg,
            ["--socket", "0.0.0.0:443", "--host", "b.example"])
        self.assertEqual(data["value"], '"hostb"')
        rc, data, _ = self.query_json(
            "server.name", cfg,
            ["--socket", "0.0.0.0:80", "--host", "b.example"])
        self.assertEqual(data["value"], '"port80"')

    def test_previous_branch_unknown_makes_bare_else_unknown(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '} else {\n'
            '  server.name = "other"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")

    def test_orphan_else_poisons(self):
        cfg = self.conf(
            'server.name = "root"\n'
            'else {\n'
            '  server.name = "orphan"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT13"))

    def test_double_pipe_header_is_unparseable_poison(self):
        cfg = self.conf(
            '$HTTP["host"] == "a" || $HTTP["host"] == "b" {\n'
            '  server.name = "either"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "a"])
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT23"))

    def test_if_prefix_and_elif_spelling_parse(self):
        cfg = self.conf(
            'if $HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '} elsif $HTTP["host"] == "b.example" {\n'
            '  server.name = "b"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "b.example"])
        self.assertEqual(data["value"], '"b"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"a"')

    def test_else_if_two_token_spelling(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '} else if $HTTP["host"] == "b.example" {\n'
            '  server.name = "b"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "b.example"])
        self.assertEqual(data["value"], '"b"')


# ------------------------------------------------------------------- BG5

class BG5ThreeValued(TmpTree):
    def test_unsupplied_host_unknown_after_root(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(data["blocker"]["line"], 3)
        self.assertEqual(data["blocker"]["kind"], "unknown-scope")

    def test_unknown_before_true_decider_is_absorbed(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n'
            '$HTTP["url"] == "/x" {\n'
            '  server.document-root = "/var/x"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--url", "/x"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/x"')
        self.assertTrue(self.has_finding(data, "absorbed"))

    def test_parent_unknown_makes_child_unknown(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.name = "nested"\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/x"])
        self.assertEqual(data["verdict"], "UNKNOWN")

    def test_no_true_plus_one_unknown_is_unknown(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(data["blocker"]["line"], 2)

    def test_chain_lists_true_false_unknown(self):
        cfg = self.conf(
            'server.name = "root"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '}\n'
            '$HTTP["url"] == "/x" {\n'
            '  server.name = "x"\n'
            '}\n')
        rc, out, _ = self.query("server.name", cfg,
                                ["--url", "/x"])
        self.assertIn("[TRUE]", out)
        self.assertIn("[UNKNOWN]", out)
        rc, out, _ = self.query("server.name", cfg,
                                ["--host", "a.example",
                                 "--url", "/x"])
        self.assertIn("[TRUE]", out)
        self.assertNotIn("[UNKNOWN]", out)


# ------------------------------------------------------------------- BG6

class BG6Includes(TmpTree):
    def test_include_at_root(self):
        sub = self.write("vhosts/a.conf",
                         'server.document-root = "/var/a"\n')
        cfg = self.conf('include "vhosts/a.conf"\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/a"')
        self.assertEqual(data["decider"]["where"], sub + ":1")

    def test_include_inside_host_block_is_conditional(self):
        sub = self.write("vhosts/a.conf",
                         'server.document-root = "/var/a"\n')
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  include "vhosts/a.conf"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"/var/a"')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_relative_include_resolves_against_main_dir(self):
        # LT03 fixture: the including file lives in vhosts/ and has a
        # decoy conf.d/b.conf next to it; the daemon reads the main
        # file's conf.d/b.conf instead.
        self.write("vhosts/conf.d/b.conf",
                   'server.name = "decoy"\n')
        self.write("conf.d/b.conf", 'server.name = "real"\n')
        self.write("vhosts/v.conf", 'include "conf.d/b.conf"\n')
        cfg = self.conf('include "vhosts/v.conf"\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(data["value"], '"real"')
        self.assertTrue(self.has_finding(data, "LT03"))

    def test_glob_sorted_order_decides_same_scope_duplicate(self):
        self.write("conf.d/b.conf", 'server.port = 81\n')
        self.write("conf.d/a.conf", 'server.port = 80\n')
        cfg = self.conf('include "%s/conf.d/*.conf"\n' % self.tmp)
        rc, data, _ = self.query_json("server.port", cfg)
        # sorted: a.conf (80) then b.conf (81); later wins.
        self.assertEqual(data["value"], "81")
        self.assertIn(os.path.join(self.tmp, "conf.d/a.conf"),
                      [f["path"] for f in
                       data["coverage"]["files_read"]])
        self.assertIn(os.path.join(self.tmp, "conf.d/b.conf"),
                      [f["path"] for f in
                       data["coverage"]["files_read"]])

    def test_glob_no_match_is_warning_not_fatal(self):
        cfg = self.conf(
            'include "%s/empty/*.conf"\n'
            'server.port = 80\n' % self.tmp)
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(data["value"], "80")
        self.assertTrue(self.has_finding(data, "matched nothing"))

    def test_missing_literal_include_is_exit_2(self):
        cfg = self.conf('include "no-such-file.conf"\n')
        rc, out, err = self.query("server.port", cfg)
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)

    def test_include_cycle_is_exit_2(self):
        self.write("a.conf", 'include "b.conf"\n')
        self.write("b.conf", 'include "a.conf"\n')
        cfg = self.conf('include "a.conf"\n')
        rc, out, err = self.query("server.port", cfg)
        self.assertEqual(rc, 2)
        self.assertIn("cycle", err)

    def test_global_block_lifts_out_of_conditional_include(self):
        self.write("vhosts/a.conf",
                   'global {\n'
                   '  server.modules = ( "mod_fastcgi" )\n'
                   '}\n'
                   'server.name = "vhost-only"\n')
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  include "vhosts/a.conf"\n'
            '}\n')
        # The global{} assignment is root-scope: it applies even
        # when the host does not match.
        rc, data, _ = self.query_json("server.modules", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["value"], '( "mod_fastcgi" )')
        self.assertEqual(data["decider"]["scope"], "root")
        # The file's plain assignment stays conditional.
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(data["verdict"], "NOT-SET")
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"vhost-only"')

    def test_multiple_conf_concatenation_per_root_bases(self):
        self.write("one/extra.conf", 'server.port = 81\n')
        self.write("two/extra.conf", 'server.port = 82\n')
        one = self.write("one/lighttpd.conf",
                         'include "extra.conf"\n')
        two = self.write("two/lighttpd.conf",
                         'include "extra.conf"\n')
        rc, data, _ = self.query_json(
            "server.port", None, conf_args=["--conf", one,
                                            "--conf", two])
        self.assertEqual(data["value"], "82")
        self.assertEqual(data["decider"]["where"],
                         os.path.join(self.tmp, "two/extra.conf")
                         + ":1")

    def test_absolute_include(self):
        sub = self.write("abs.conf", 'server.port = 8080\n')
        cfg = self.conf('include "%s"\n' % sub)
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(data["value"], "8080")

# ------------------------------------------------------------------- BG7

class BG7VarEnvShell(TmpTree):
    def test_var_used_in_value_and_include_path(self):
        sub = self.write("vhosts/x.conf",
                         'server.document-root = "/var/x"\n')
        cfg = self.conf(
            'var.dir = "vhosts"\n'
            'include var.dir + "/x.conf"\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["value"], '"/var/x"')
        self.assertEqual(data["decider"]["where"], sub + ":1")

    def test_var_used_in_value(self):
        cfg = self.conf(
            'var.base = "/var"\n'
            'server.document-root = var.base + "/www"\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["value"], '"/var/www"')

    def test_var_redefinition_later_uses_see_later_value(self):
        cfg = self.conf(
            'var.x = "one"\n'
            'server.name = var.x\n'
            'var.x = "two"\n'
            'server.port = 80\n'
            'server.name = var.x\n')
        rc, data, _ = self.query_json("server.name", cfg)
        # The later assignment (line 5) is the decider and sees "two".
        self.assertEqual(data["value"], '"two"')
        self.assertEqual(data["decider"]["where"], cfg + ":5")

    def test_use_before_definition_poisons(self):
        cfg = self.conf(
            'server.name = var.undefined\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT23"))

    def test_concat_literal_var_and_option_reference(self):
        cfg = self.conf(
            'server.name = "host1"\n'
            'var.base = "/var"\n'
            'server.document-root = var.base + "/" + server.name\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["value"], '"/var/host1"')

    def test_var_pid_renders_placeholder_stays_effective(self):
        cfg = self.conf('server.name = var.PID\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], "<PID-unknown>")
        self.assertTrue(
            data["coverage"]["dependencies"]["var_pid"])

    def test_var_cwd_with_and_without_flag(self):
        cfg = self.conf(
            'server.document-root = var.CWD + "/www"\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--cwd", "/srv"])
        self.assertEqual(data["value"], '"/srv/www"')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["value"], '"<CWD-unknown>/www"')
        self.assertTrue(
            data["coverage"]["dependencies"]["var_cwd"])

    def test_env_comes_only_from_flag_never_from_process_env(self):
        # The harness exports the trap variable into the tool's own
        # environment; the tool must NOT read it (LT07/LT26).
        env = dict(os.environ)
        env[TRAP_ENV] = "leaked-value"
        cfg = self.conf('server.name = env.%s\n' % TRAP_ENV)
        rc, out, err = run_cli(
            ["server.name", "--conf", cfg, "--json"], env=env)
        data = json.loads(out)
        self.assertEqual(data["value"],
                         "<env:%s-unknown>" % TRAP_ENV)
        rc, out, err = run_cli(
            ["server.name", "--conf", cfg, "--json",
             "--env", "%s=from-flag" % TRAP_ENV], env=env)
        data = json.loads(out)
        self.assertEqual(data["value"], '"from-flag"')

    def test_env_unknown_in_value_stays_effective_with_finding(self):
        cfg = self.conf('server.name = env.MISSING_VAR\n')
        rc, data, _ = self.query_json("server.name", cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], "<env:MISSING_VAR-unknown>")
        self.assertTrue(self.has_finding(data, "LT07"))

    def test_env_unknown_include_path_poisons(self):
        cfg = self.conf('include env.MISSING_DIR + "/x.conf"\n')
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT07"))

    def test_env_unknown_condition_value_is_unknown(self):
        cfg = self.conf(
            '$HTTP["host"] == env.EXPECTED_HOST {\n'
            '  server.name = "gated"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["verdict"], "UNKNOWN")

    def test_include_shell_with_no_later_decider_is_unknown(self):
        cfg = self.conf(
            'include_shell "cat /etc/lighttpd/vhosts.d/*.conf"\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(data["blocker"]["kind"], "include_shell")
        self.assertEqual(data["blocker"]["line"], 1)
        self.assertEqual(
            len(data["unmodeled"]["include_shell"]), 1)
        self.assertIn("cat /etc/lighttpd/vhosts.d/*.conf",
                      data["unmodeled"]["include_shell"][0]["command"])

    def test_include_shell_absorbed_by_later_decider(self):
        cfg = self.conf(
            'include_shell "generate-vhosts.pl"\n'
            'server.document-root = "/var/www"\n')
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/www"')
        self.assertTrue(self.has_finding(data, "absorbed"))

    def test_include_shell_in_false_scope_is_harmless(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  include_shell "generate-vhosts.pl"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "c.example"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], '"/var/www"')

    def test_include_shell_never_executes(self):
        marker = os.path.join(self.tmp, "marker.txt")
        cfg = self.conf(
            'include_shell "touch %s"\n' % marker)
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertFalse(os.path.exists(marker),
                         "include_shell was executed!")

    def test_include_shell_in_comment_and_script_path_not_run(self):
        # Payloads in comments and in script-path values must not run.
        marker = os.path.join(self.tmp, "marker2.txt")
        cfg = self.conf(
            '# include_shell "touch %s"\n'
            'server.document-root = "/var/www"\n'
            'fastcgi.server = ( ".php" => ( ( "bin-path" => '
            '"/bin/touch %s" ) ) )\n' % (marker, marker))
        rc, data, _ = self.query_json("server.document-root", cfg)
        self.assertEqual(data["value"], '"/var/www"')
        self.assertFalse(os.path.exists(marker))


# ------------------------------------------------------------------- BG8

class BG8Regex(TmpTree):
    def test_common_subset_patterns_evaluate(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "^/v[0-9]+/(users|posts)/[0-9]+$" {\n'
            '  server.name = "api"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/v2/users/42"])
        self.assertEqual(data["value"], '"api"')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/v2/other/42"])
        self.assertEqual(data["verdict"], "NOT-SET")

    def test_regex_is_unanchored_search(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "download" {\n'
            '  server.name = "dl"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/files/download/x"])
        self.assertEqual(data["value"], '"dl"')

    def test_lookbehind_is_regex_unknown(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "(?<=foo)bar" {\n'
            '  server.name = "lb"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "foobar"])
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(len(data["unmodeled"]["regex_unknown"]), 1)

    def test_possessive_quantifier_is_regex_unknown(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "a++b" {\n'
            '  server.name = "poss"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "aaab"])
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(len(data["unmodeled"]["regex_unknown"]), 1)

    def test_invalid_regex_poisons_scope(self):
        cfg = self.conf(
            '$HTTP["url"] =~ "(unclosed" {\n'
            '  server.name = "bad"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/x"])
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertTrue(self.has_finding(data, "LT23"))

    def test_capture_tokens_rendered_verbatim(self):
        cfg = self.conf(
            '$HTTP["host"] =~ "^(.*)\\\\.example" {\n'
            '  server.document-root = "/var/%1/$1"\n'
            '}\n')
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(data["value"], '"/var/%1/$1"')
        self.assertTrue(
            self.has_finding(data, "capture-substitution"))


# ------------------------------------------------------------------- BG9

class BG9DynamismCoverageSafety(TmpTree):
    def _vhost_cfg(self):
        return self.conf(
            'server.modules = ( "mod_simple_vhost" )\n'
            'server.document-root = "/var/www"\n'
            'server.port = 80\n')

    def test_simple_vhost_makes_document_root_unknown(self):
        cfg = self._vhost_cfg()
        rc, data, _ = self.query_json("server.document-root", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(rc, 1)
        self.assertEqual(data["verdict"], "UNKNOWN")
        self.assertEqual(data["blocker"]["kind"], "runtime-vhost")
        self.assertEqual(data["blocker"]["line"], 1)
        self.assertTrue(self.has_finding(data, "LT25"))

    def test_simple_vhost_other_key_stays_effective_with_banner(self):
        cfg = self._vhost_cfg()
        rc, data, _ = self.query_json("server.port", cfg,
                                      ["--host", "a.example"])
        self.assertEqual(rc, 0)
        self.assertEqual(data["verdict"], "EFFECTIVE")
        self.assertEqual(data["value"], "80")
        self.assertTrue(self.has_finding(data, "LT25"))

    def test_extforward_remoteip_banner(self):
        cfg = self.conf(
            'server.modules = ( "mod_extforward" )\n'
            '$HTTP["remoteip"] == "10.0.0.0/8" {\n'
            '  server.name = "internal"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--remoteip", "10.1.2.3"])
        self.assertEqual(data["value"], '"internal"')
        self.assertTrue(
            self.has_finding(data, "peer-ip-may-be-rewritten"))

    def test_url_normalization_finding(self):
        cfg = self.conf(
            '$HTTP["url"] == "/a/b" {\n'
            '  server.name = "ab"\n'
            '}\n')
        rc, data, _ = self.query_json("server.name", cfg,
                                      ["--url", "/a/../b"])
        self.assertTrue(
            self.has_finding(data, "url-normalization-not-modeled"))

    def test_list_conditions(self):
        cfg = self.conf(
            'server.port = 80\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '  $HTTP["url"] == "/x" {\n'
            '    server.name = "ax"\n'
            '  }\n'
            '} else {\n'
            '  server.name = "other"\n'
            '}\n')
        rc, out, _ = run_cli(["--list-conditions", "--conf", cfg])
        self.assertEqual(rc, 0)
        self.assertIn('$HTTP["host"] == "a.example"', out)
        self.assertIn('$HTTP["url"] == "/x"', out)
        self.assertIn("else", out)
        self.assertIn("server.document-root", out)
        rc, out, _ = run_cli(["--list-conditions", "--conf", cfg,
                              "--json"])
        data = json.loads(out)
        self.assertEqual(len(data["conditions"]), 3)
        rc, out, _ = run_cli(
            ["--list-conditions", "--conf",
             self.conf('server.port = 80\n')])
        self.assertEqual(rc, 1)

    def test_list_conditions_merge_note(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a1"\n'
            '}\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a2"\n'
            '}\n')
        rc, out, _ = run_cli(["--list-conditions", "--conf", cfg])
        self.assertEqual(rc, 0)
        self.assertIn("merged with identical block", out)

    def test_list_keys(self):
        cfg = self.conf(
            'server.port = 80\n'
            'server.port = 81\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.port = 8080\n'
            '  server.name = "a"\n'
            '}\n')
        rc, out, _ = run_cli(["--list-keys", "--conf", cfg])
        self.assertEqual(rc, 0)
        self.assertIn("server.port", out)
        self.assertIn("3 assignments", out)
        self.assertIn("server.name", out)
        rc, out, _ = run_cli(["--list-keys", "--conf", cfg, "--json"])
        data = json.loads(out)
        self.assertEqual(len(data["keys"]), 2)
        rc, out, _ = run_cli(
            ["--list-keys", "--conf", self.conf("# nothing\n")])
        self.assertEqual(rc, 1)

    def test_json_fidelity_vs_text(self):
        cfg = self.conf(
            'server.document-root = "/var/www"\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.document-root = "/var/a"\n'
            '}\n')
        for extra in (["--host", "a.example"], ["--host", "c.example"],
                      []):
            rc_t, out_t, _ = self.query("server.document-root", cfg,
                                        extra)
            rc_j, data, _ = self.query_json("server.document-root",
                                            cfg, extra)
            self.assertEqual(rc_t, rc_j)
            self.assertEqual(out_t.splitlines()[0], data["verdict"])

    def test_coverage_completeness(self):
        sub = self.write("inc.conf", 'server.port = 81\n')
        cfg = self.conf(
            'include "inc.conf"\n'
            'server.port = 80\n'
            '$HTTP["host"] == "a.example" {\n'
            '  server.name = "a"\n'
            '}\n')
        rc, data, _ = self.query_json("server.port", cfg,
                                      ["--host", "a.example"])
        cov = data["coverage"]
        paths = [f["path"] for f in cov["files_read"]]
        self.assertIn(cfg, paths)
        self.assertIn(sub, paths)
        self.assertEqual(len(cov["includes"]), 1)
        self.assertEqual(cov["scopes"]["condition"], 1)
        self.assertEqual(cov["keys_assigned"], 2)
        self.assertEqual(cov["assignments"], 3)
        self.assertEqual(cov["unparseable_lines"], 0)

    def test_version(self):
        rc, out, _ = run_cli(["--version"])
        self.assertEqual(rc, 0)
        self.assertIn("lighttpdwho 1.0.0", out)

    def test_array_and_keylist_values_render(self):
        cfg = self.conf(
            'url.access-deny = ( ".php", ".pl" )\n'
            'fastcgi.server = ( ".php" => ( ( "socket" => '
            '"/tmp/php.sock" ) ) )\n')
        rc, data, _ = self.query_json("url.access-deny", cfg)
        self.assertEqual(data["value"], '( ".php", ".pl" )')
        rc, data, _ = self.query_json("fastcgi.server", cfg)
        self.assertIn('"socket" => "/tmp/php.sock"',
                      data["value"])

    def test_comments_and_multiline_arrays_parse(self):
        cfg = self.conf(
            '# a comment line\n'
            'server.modules = (\n'
            '  "mod_a", # trailing comment\n'
            '  "mod_b"\n'
            ')\n')
        rc, data, _ = self.query_json("server.modules", cfg)
        self.assertEqual(data["value"], '( "mod_a", "mod_b" )')

    def test_garbage_line_is_warning_not_poison(self):
        cfg = self.conf(
            'server.port = 80\n'
            'this is not a directive\n'
            'server.name = "ok"\n')
        rc, data, _ = self.query_json("server.port", cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(data["value"], "80")
        self.assertTrue(self.has_finding(data, "LT23"))
        self.assertEqual(data["coverage"]["unparseable_lines"], 1)

    def test_socket_block_nested_inside_condition_finding(self):
        cfg = self.conf(
            '$HTTP["host"] == "a.example" {\n'
            '  $SERVER["socket"] == ":80" {\n'
            '    server.name = "nested-sock"\n'
            '  }\n'
            '}\n')
        rc, data, _ = self.query_json(
            "server.name", cfg,
            ["--host", "a.example", "--socket", "0.0.0.0:80"])
        self.assertEqual(data["value"], '"nested-sock"')
        self.assertTrue(self.has_finding(data, "LT20"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
