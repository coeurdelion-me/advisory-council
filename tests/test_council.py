#!/usr/bin/env python3
"""Tests for council.py. Standard library only: python3 -m unittest discover -s council/tests -v

The end-to-end cases run the real command against a fake OpenAI-compatible server on localhost, so
the provider path (URL, auth header, request body, error handling) is exercised without spending
anything. The fake server records what it received, which is how the tests prove, for example, that
`reasoning` reaches a provider that lists it and is withheld from one that does not.
"""
import http.server
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "advisory-council" / "scripts" / "council.py"
spec = importlib.util.spec_from_file_location("council", SCRIPT)
council = importlib.util.module_from_spec(spec)
spec.loader.exec_module(council)

QUESTIONS_OUTPUT = """## A
""" + "\n".join(f"{i}. Question number {i}?\n   What turns on it: the verdict moves." for i in range(1, 11)) + """

## B
Cannot assess the accounts.

## C
Utilisation, the cost of theft, and staff time.
"""


class Fake(http.server.BaseHTTPRequestHandler):
    log = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.log.append({"path": self.path, "auth": self.headers.get("Authorization"),
                         "ua": self.headers.get("User-Agent"), "body": body})
        if Fake.mode == "401":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"bad key"}')
            return
        if Fake.mode == "mixed" and body["model"] == "m-two":      # a malformed reply from one seat
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": "oops"}], "usage": 5}).encode())
            return
        content = "" if Fake.mode == "empty" else QUESTIONS_OUTPUT
        if Fake.mode == "cut":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "Half an arg"},
                             "finish_reason": "length"}], "usage": {}}).encode())
            return
        if Fake.mode == "parts":                                    # OpenAI content-parts format
            content = [{"type": "text", "text": QUESTIONS_OUTPUT}]
        payload = {"choices": [{"message": {"content": content, "reasoning": "thinking"},
                                "finish_reason": "length" if Fake.mode == "empty" else "stop"}],
                   "usage": {"prompt_tokens": 50, "completion_tokens": 20}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


class Server:
    def __enter__(self):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        Fake.log, Fake.mode = [], "ok"
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_config(d, port, key_env="TEST_COUNCIL_KEY", allow_reasoning=True):
    prov = d / "providers.toml"
    prov.write_text(f'''default = "fake"
[providers.fake]
base_url = "http://127.0.0.1:{port}/v1"
{f'key_env = "{key_env}"' if key_env else ""}
{'body_fields = ["reasoning"]' if allow_reasoning else ''}
''')
    panel = d / "panel.toml"
    panel.write_text('''name = "t"
[[seat]]
name = "One"
model = "m-one"
max_tokens = 100
timeout = 20
reasoning = { effort = "low" }
persona = "You are reviewer one."
[[seat]]
name = "Two"
model = "m-two"
max_tokens = 100
timeout = 20
persona = "You are reviewer two."
''')
    brief = d / "brief.md"
    brief.write_text("# A tiny brief\n")
    return prov, panel, brief


def run(d, prov, panel, brief, *extra, env=None):
    e = {k: v for k, v in os.environ.items() if k != "TEST_COUNCIL_KEY"}
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--brief", str(brief), "--outdir", str(d / "out"),
                           "--panel", str(panel), "--providers", str(prov), *extra],
                          capture_output=True, text=True, env=e)


class Compliance(unittest.TestCase):
    def test_compliant_questions_round(self):
        c = council.compliance(QUESTIONS_OUTPUT, "questions", 10)
        self.assertEqual(c["sections_found"], ["A", "B", "C"])
        self.assertEqual(c["questions_enumerated"], 10)
        self.assertEqual(c["verdict"], "within cap")
        self.assertEqual(c["counted_in"], "section A")

    def test_self_capping_seat_is_flagged_under(self):
        short = "## A\n1. Only one?\n\n## B\nx\n\n## C\ny\n"
        self.assertTrue(council.compliance(short, "questions", 10)["verdict"].startswith("UNDER cap"))

    def test_over_cap_is_flagged(self):
        many = "## A\n" + "\n".join(f"{i}. q{i}?" for i in range(1, 15)) + "\n## B\nx\n## C\ny\n"
        self.assertTrue(council.compliance(many, "questions", 10)["verdict"].startswith("OVER cap"))

    def test_missing_sections_are_named(self):
        c = council.compliance("## A\n1. q?\n2. q?\n3. q?\n4. q?\n5. q?\n", "questions", 10)
        self.assertEqual(c["sections_missing"], ["B", "C"])
        self.assertIn("sections missing: B,C", c["verdict"])

    def test_a_heading_that_only_starts_with_a_letter_is_not_a_section(self):
        for text in ("## A note on scope", "## A. Overview", "## a lowercase heading test",
                     "#### B: Something"):
            self.assertIsNone(council.SECTION_RE.search(text), text)

    def test_bare_and_labelled_forms_match(self):
        for text, want in (("### C", "C"), ("## A", "A"), ("## A:", "A"), ("## A.", "A"),
                           ("## Section A", "A"), ("**Section B**", "B")):
            m = council.SECTION_RE.search(text)
            self.assertIsNotNone(m, text)
            self.assertEqual(council.section_letter(m).upper(), want, text)

    def test_verdict_round_is_not_counted(self):
        self.assertEqual(council.compliance("anything", "verdict", 10)["verdict"],
                         "n/a (not a questions round)")


class Output(unittest.TestCase):
    R = {"seat": "S", "model": "m", "provider": "p", "content": "Body.\n",
         "prompt_tokens": 1, "completion_tokens": 2, "seconds": 0.5, "finish_reason": "stop"}

    def test_seat_markdown_keeps_model_text_byte_identical(self):
        self.assertTrue(council.seat_markdown(self.R).endswith("\n\nBody.\n\n"))
        self.assertIn("<!-- seat: S | model: m | provider: p", council.seat_markdown(self.R))

    def test_slug(self):
        self.assertEqual(council.slug("Devil's Advocate"), "devil-s-advocate")


class Config(unittest.TestCase):
    def test_every_shipped_panel_loads_with_the_shipped_providers(self):
        providers = council.load_toml(council.CONFIG / "providers.toml")
        for path in sorted((council.CONFIG / "panels").glob("*.toml")):
            seats, order, synth = council.load_panel(path, providers, "openrouter")
            self.assertEqual(len(order), 4, path.name)
            self.assertIsNotNone(synth, path.name)
            for s in seats.values():
                self.assertTrue(s["system"], f"{path.name}: {s['seat']} has no persona")

    def test_personas_carry_no_round_instruction(self):
        providers = council.load_toml(council.CONFIG / "providers.toml")
        for path in sorted((council.CONFIG / "panels").glob("*.toml")):
            seats, _, _ = council.load_panel(path, providers, "openrouter")
            for s in seats.values():
                for banned in ("3-5", "most important issues", "at most", "issues only"):
                    self.assertNotIn(banned, s["system"], f"{path.name}: {s['seat']}")

    def test_unknown_seat_field_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / "p.toml"
            p.write_text('[[seat]]\nname="A"\nmodel="m"\nmax_tokens=1\ntimeout=1\npersona="x"\ntypo=1\n')
            with self.assertRaises(SystemExit) as cm:
                council.load_panel(p, {"providers": {"x": {}}}, "x")
            self.assertIn("unknown field", str(cm.exception))

    def test_seat_with_no_persona_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "p.toml"
            p.write_text('[[seat]]\nname="A"\nmodel="m"\nmax_tokens=1\ntimeout=1\n')
            with self.assertRaises(SystemExit) as cm:
                council.load_panel(p, {"providers": {"x": {}}}, "x")
            self.assertIn("no persona", str(cm.exception))

    def test_seat_naming_an_undefined_provider_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "p.toml"
            p.write_text('[[seat]]\nname="A"\nmodel="m"\nprovider="nope"\nmax_tokens=1\ntimeout=1\npersona="x"\n')
            with self.assertRaises(SystemExit) as cm:
                council.load_panel(p, {"providers": {"x": {}}}, "x")
            self.assertIn("not in the providers file", str(cm.exception))

    def _panel_error(self, body, providers=None):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "p.toml"
            p.write_text(body)
            with self.assertRaises(SystemExit) as cm:
                council.load_panel(p, providers or {"providers": {"x": {}}}, "x")
            return str(cm.exception)

    SEAT = 'name="%s"\nmodel="m"\nmax_tokens=%s\ntimeout=1\npersona="x"\n'

    def test_duplicate_seat_names_are_refused(self):
        msg = self._panel_error("[[seat]]\n" + self.SEAT % ("The Client", 1) + "[[seat]]\n" + self.SEAT % ("client", 1))
        self.assertIn("two seats are called", msg)

    def test_a_seat_name_that_collides_with_a_runner_file_is_refused(self):
        self.assertIn("collide", self._panel_error("[[seat]]\n" + self.SEAT % ("Synthesis", 1)))

    def test_wrong_value_types_exit_with_a_message_not_a_traceback(self):
        self.assertIn("positive integer", self._panel_error("[[seat]]\n" + self.SEAT % ("A", '"lots"')))

    def test_shipped_files_contain_no_key_material(self):
        for p in list((ROOT / "skills" / "advisory-council" / "config").rglob("*.toml")):
            text = p.read_text()
            self.assertNotRegex(text, r"sk-[A-Za-z0-9]{10,}", p.name)
            self.assertNotRegex(text, r"(?i)bearer\s+[A-Za-z0-9]{10,}", p.name)


class EndToEnd(unittest.TestCase):
    def test_a_run_reaches_the_provider_with_the_key_and_writes_every_artefact(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            r = run(d, prov, panel, brief, "--round-shape", "questions",
                    env={"TEST_COUNCIL_KEY": "secret-test-value"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(Fake.log), 2)
            for call in Fake.log:
                self.assertEqual(call["path"], "/v1/chat/completions")
                self.assertEqual(call["auth"], "Bearer secret-test-value")
                self.assertTrue(call["ua"].startswith("advisory-council/"))
                # the round shape is in the SYSTEM prompt, not the brief
                self.assertIn("Section A", call["body"]["messages"][0]["content"])
                self.assertNotIn("Section A", call["body"]["messages"][1]["content"])
            out = d / "out"
            for name in ("one.md", "two.md", "panel-as-run.json", "run-log.json"):
                self.assertTrue((out / name).exists(), name)
            self.assertIn("Question number 1?", (out / "one.md").read_text())
            self.assertNotIn("secret-test-value", (out / "run-log.json").read_text())
            self.assertNotIn("secret-test-value", (out / "panel-as-run.json").read_text())
            self.assertNotIn("secret-test-value", r.stdout + r.stderr)

    def test_reasoning_reaches_only_a_provider_that_lists_it(self):
        for allow, expect in ((True, True), (False, False)):
            with Server() as s, tempfile.TemporaryDirectory() as t:
                d = pathlib.Path(t)
                prov, panel, brief = write_config(d, s.port, allow_reasoning=allow)
                r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                one = next(c for c in Fake.log if c["body"]["model"] == "m-one")
                two = next(c for c in Fake.log if c["body"]["model"] == "m-two")
                self.assertEqual("reasoning" in one["body"], expect)
                self.assertNotIn("reasoning", two["body"])

    def test_a_keyless_provider_sends_no_authorization_header(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port, key_env=None)
            r = run(d, prov, panel, brief)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(all(c["auth"] is None for c in Fake.log))

    def test_missing_key_refuses_before_anything_is_sent(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            r = run(d, prov, panel, brief)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("TEST_COUNCIL_KEY", r.stdout + r.stderr)
            self.assertEqual(Fake.log, [])
            self.assertFalse((d / "out").exists())

    def test_dry_run_calls_nothing_and_writes_nothing(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            r = run(d, prov, panel, brief, "--dry-run")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(Fake.log, [])
            self.assertFalse((d / "out").exists())
            self.assertIn("DATA:", r.stdout)

    def test_max_cost_refuses_when_a_price_is_unknown(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            r = run(d, prov, panel, brief, "--max-cost", "1", env={"TEST_COUNCIL_KEY": "k"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no known price", r.stdout + r.stderr)
            self.assertEqual(Fake.log, [])

    def test_bad_key_is_reported_per_seat_and_the_failed_seats_can_be_rerun(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "401"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "wrong"})
            self.assertEqual(r.returncode, 1)
            self.assertIn("HTTP 401", r.stdout)
            self.assertIn("--only", r.stdout)
            Fake.mode = "ok"
            r2 = run(d, prov, panel, brief, "--only", "Two", env={"TEST_COUNCIL_KEY": "right"})
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertTrue((d / "out" / "two.md").exists())
            self.assertFalse((d / "out" / "one.md").exists())

    def test_empty_content_is_a_failure_not_a_blank_file(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "empty"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 1)
            self.assertIn("empty content returned", r.stdout)
            self.assertFalse((d / "out" / "one.md").exists())
            log = json.loads((d / "out" / "run-log.json").read_text())
            res = log[0]["results"][0]
            self.assertEqual(res["finish_reason"], "length")
            self.assertIn("reasoning", res["message_keys"])

    def test_a_malformed_reply_from_one_seat_does_not_lose_the_others(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "mixed"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertTrue((d / "out" / "one.md").exists())
            self.assertFalse((d / "out" / "two.md").exists())
            self.assertIn("no choices[0].message", r.stdout)

    def test_a_reply_cut_off_at_max_tokens_is_warned_about(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "cut"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertIn("cut off at max_tokens", r.stdout)

    def test_content_parts_replies_are_joined(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "parts"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Question number 1?", (d / "out" / "one.md").read_text())

    def test_a_401_body_is_not_kept(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            Fake.mode = "401"
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertNotIn("bad key", r.stdout + (d / "out" / "run-log.json").read_text())

    def test_synthesise_dry_run_calls_nothing(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            panel.write_text(panel.read_text() + '''
[synthesiser]
model = "m-synth"
max_tokens = 100
timeout = 20
persona = "You aggregate."
''')
            run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            Fake.log.clear()
            r = run(d, prov, panel, brief, "--synthesise", "--dry-run", env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(Fake.log, [])
            self.assertFalse((d / "out" / "synthesis.md").exists())
            r = run(d, prov, panel, brief, "--synthesise", "--max-cost", "1", env={"TEST_COUNCIL_KEY": "k"})
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(Fake.log, [])

    def test_an_unreachable_provider_fails_loudly_per_seat(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, 1)       # nothing listens on port 1
            r = run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 1)
            self.assertIn("FAILED", r.stdout)

    def test_synthesis_reads_seat_outputs_and_leaves_them_untouched(self):
        with Server() as s, tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            prov, panel, brief = write_config(d, s.port)
            panel.write_text(panel.read_text() + '''
[synthesiser]
model = "m-synth"
max_tokens = 100
timeout = 20
persona = "You aggregate."
''')
            run(d, prov, panel, brief, env={"TEST_COUNCIL_KEY": "k"})
            before = (d / "out" / "one.md").read_bytes()
            Fake.log.clear()
            r = run(d, prov, panel, brief, "--synthesise", env={"TEST_COUNCIL_KEY": "k"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(Fake.log[0]["body"]["model"], "m-synth")
            self.assertIn("one.md", Fake.log[0]["body"]["messages"][1]["content"] + "one.md")
            self.assertTrue((d / "out" / "synthesis.md").exists())
            self.assertEqual((d / "out" / "one.md").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
