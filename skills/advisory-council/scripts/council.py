#!/usr/bin/env python3
"""Convene a panel of language models over any OpenAI-compatible API and keep every raw output.

Usage:
  council.py --brief brief-round1.md --outdir round1 --round-shape questions --dry-run
  council.py --brief brief-round1.md --outdir round1 --round-shape questions --max-questions 10
  council.py --brief brief-round2.md --outdir round2 --round-shape verdict --max-cost 3
  council.py --brief b.md --outdir round1 --only "The Client" --timeout 1500    # re-run one seat
  council.py --brief brief-round2.md --outdir round2 --synthesise               # model synthesis

Requires Python 3.11 or later. Standard library only.

Providers, panels and round shapes are plain TOML files (see config/). A seat names a model and,
optionally, a provider; a provider names a base URL and the environment variable that holds the
key. Keys are read from the environment and nowhere else.

The round shape (questions or verdict) is appended to each seat's SYSTEM prompt, not the brief.
A reviewer obeys instructions that arrive as its role and may refuse the same instructions when
they arrive inside the document it was asked to review.
"""
import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from urllib.parse import urlparse

if sys.version_info < (3, 11):
    sys.exit("council.py needs Python 3.11 or later (it uses the standard-library tomllib).")

__version__ = "0.1.0"

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE.parent / "config"
USER_AGENT = f"advisory-council/{__version__}"

# Rough, and stated as rough. Only the pre-run estimate uses it; what a run actually cost is in
# the usage figures of run-log.json.
CHARS_PER_TOKEN = 4


# --------------------------------------------------------------------------- configuration

def load_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        sys.exit(f"config file not found: {path}")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"config file is not valid TOML: {path}: {e}")


def find_providers(explicit):
    """--providers, then $COUNCIL_PROVIDERS, then ./council.providers.toml, then the shipped file."""
    for cand in (explicit, os.environ.get("COUNCIL_PROVIDERS"),
                 "council.providers.toml" if pathlib.Path("council.providers.toml").exists() else None):
        if cand:
            return pathlib.Path(cand)
    return CONFIG / "providers.toml"


def find_panel(name):
    """A path, or a name looked up in ./panels/ and then in the shipped panels."""
    p = pathlib.Path(name)
    if p.suffix == ".toml" and p.exists():
        return p
    for base in (pathlib.Path("panels"), CONFIG / "panels"):
        cand = base / f"{name}.toml"
        if cand.exists():
            return cand
    shipped = sorted(x.stem for x in (CONFIG / "panels").glob("*.toml"))
    sys.exit(f"no panel named {name!r}. Shipped panels: {', '.join(shipped)}. "
             f"Or pass the path to your own .toml file.")


RESERVED_FILES = {"synthesis", "panel-as-run", "run-log"}
SEAT_FIELDS = {"name", "model", "provider", "role", "status", "max_tokens", "timeout",
               "reasoning", "persona"}


def _norm(seat):
    return re.sub(r"^the\s+", "", seat.strip().lower())


def load_panel(path, providers, default_provider):
    """Return (seats, order, synth). Fails loudly on every miss: a seat that silently loses its
    persona produces a plausible review from the wrong reviewer, which is worse than none."""
    d = load_toml(path)
    raw = d.get("seat", [])
    if not raw:
        sys.exit(f"BROKEN PANEL {path}: no [[seat]] entries.")
    seats, order = {}, []
    default_provider = d.get("default_provider", default_provider)
    for s in raw:
        unknown = set(s) - SEAT_FIELDS
        if unknown:
            sys.exit(f"BROKEN PANEL {path}: seat {s.get('name')!r} has unknown field(s) "
                     f"{sorted(unknown)}. Not guessing.")
        seat = finish_seat(s, path, providers, default_provider)
        key = _norm(seat["seat"])
        if key in seats:
            sys.exit(f"BROKEN PANEL {path}: two seats are called {seat['seat']!r} (names are compared "
                     f"without a leading 'The', ignoring case). Not guessing which you meant.")
        if slug(seat["seat"]) in {slug(v["seat"]) for v in seats.values()}:
            sys.exit(f"BROKEN PANEL {path}: seat {seat['seat']!r} would write the same output file "
                     f"as another seat.")
        if slug(seat["seat"]) in RESERVED_FILES:
            sys.exit(f"BROKEN PANEL {path}: a seat cannot be called {seat['seat']!r}; its output file "
                     f"would collide with one the runner writes.")
        seats[key] = seat
        order.append(key)
    synth = None
    if "synthesiser" in d:
        synth = finish_seat({"name": "Synthesiser", **d["synthesiser"]}, path, providers,
                            default_provider)
    return seats, order, synth


def finish_seat(s, path, providers, default_provider):
    for need in ("name", "model", "persona", "max_tokens", "timeout"):
        if not s.get(need):
            sys.exit(f"BROKEN PANEL {path}: seat {s.get('name')!r} has no {need}.")
    for field in ("name", "model", "persona"):
        if not isinstance(s[field], str):
            sys.exit(f"BROKEN PANEL {path}: seat {s['name']!r}: {field} must be text.")
    for field in ("max_tokens", "timeout"):
        if isinstance(s[field], bool) or not isinstance(s[field], int) or s[field] < 1:
            sys.exit(f"BROKEN PANEL {path}: seat {s['name']!r}: {field} must be a positive integer.")
    if s.get("reasoning") is not None and not isinstance(s["reasoning"], dict):
        sys.exit(f"BROKEN PANEL {path}: seat {s['name']!r}: reasoning must be a table.")
    prov = s.get("provider", default_provider)
    if prov not in providers["providers"]:
        sys.exit(f"BROKEN PANEL {path}: seat {s['name']!r} names provider {prov!r}, which is not "
                 f"in the providers file. Known: {sorted(providers['providers'])}")
    return {"seat": s["name"], "model": s["model"], "provider": prov,
            "role": s.get("role", ""), "status": s.get("status", "untested"),
            "max_tokens": int(s["max_tokens"]), "timeout": int(s["timeout"]),
            "reasoning": s.get("reasoning"), "system": " ".join(s["persona"].split())}


def load_shapes():
    d = load_toml(CONFIG / "round-shapes.toml")
    return {k: " ".join(v["text"].split()) for k, v in d.items()}


# --------------------------------------------------------------------------- providers

def provider_key(prov):
    """The key for a provider, from its environment variable. None when the provider needs none."""
    env = prov.get("key_env")
    if not env:
        return None
    return os.environ.get(env) or None


def key_problems(used, providers):
    """Every provider the run uses whose key is required and absent, before anything is sent."""
    out = []
    for name in sorted(used):
        prov = providers["providers"][name]
        env = prov.get("key_env")
        if env and not os.environ.get(env):
            out.append(f"{name}: set the environment variable {env}")
    return out


_price_cache = {}


def openrouter_prices(prov):
    """{model id: (input $/token, output $/token)} from the provider's public model list.
    Empty when unreachable: the estimate then degrades to token counts and never blocks a run
    unless --max-cost is set."""
    base = prov["base_url"].rstrip("/")
    if base in _price_cache:
        return _price_cache[base]
    out = {}
    try:
        req = urllib.request.Request(base + "/models", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            for m in json.load(r).get("data", []):
                p = m.get("pricing") or {}
                try:
                    out[m["id"]] = (float(p["prompt"]), float(p["completion"]))
                except (KeyError, TypeError, ValueError):
                    pass
    except Exception:
        pass
    _price_cache[base] = out
    return out


def price_for(seat, providers):
    prov = providers["providers"][seat["provider"]]
    if prov.get("pricing") == "openrouter":
        return openrouter_prices(prov).get(seat["model"])
    return None


# --------------------------------------------------------------------------- calling

def call(seat, system, brief, providers, max_tokens, timeout):
    """One seat, one call. Returns a result dict; never raises past the pool."""
    prov = providers["providers"][seat["provider"]]
    payload = {"model": seat["model"], "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": brief}]}
    if seat.get("reasoning") and "reasoning" in prov.get("body_fields", []):
        payload["reasoning"] = seat["reasoning"]
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT,
               **{k: str(v) for k, v in prov.get("headers", {}).items()}}
    key = provider_key(prov)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = prov["base_url"].rstrip("/") + "/chat/completions"
    base = {"seat": seat["seat"], "model": seat["model"], "provider": seat["provider"]}
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        # A 401 or 403 body can echo part of the credential back, so it is not kept.
        body = "(response body withheld)" if e.code in (401, 403) \
            else e.read()[:400].decode(errors="replace")
        return {**base, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": f"HTTP {e.code}: {body}"}
    except Exception as e:                       # timeout, connection reset, malformed body
        return {**base, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": f"{type(e).__name__}: {e}"}

    if not isinstance(d, dict):
        return {**base, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": "response is not a JSON object"}
    if "error" in d:
        return {**base, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": str(d["error"])[:400]}
    try:
        choice = d["choices"][0]
        msg = choice["message"]
        if not isinstance(msg, dict):
            raise TypeError
    except (KeyError, IndexError, TypeError):
        return {**base, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": "response has no choices[0].message"}
    content = msg.get("content") or ""
    if isinstance(content, list):               # the content-parts format
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    if not isinstance(content, str):
        content = ""
    usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    # When content is empty the message keys are the only diagnosis available: a reasoning model
    # that spends its whole completion budget thinking returns finish_reason 'length' with nothing
    # in content, and looks identical to a refusal unless the keys are recorded.
    return {**base, "ok": bool(content.strip()), "content": content,
            "message_keys": sorted(msg.keys()) if not content.strip() else None,
            "reasoning_chars": len(msg["reasoning"]) if isinstance(msg.get("reasoning"), str) else 0,
            "finish_reason": choice.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "seconds": round(time.time() - t0, 1),
            "error": None if content.strip() else "empty content returned"}


# --------------------------------------------------------------------------- compliance

# Three alternatives, three groups, so pick the live one with section_letter().
#  1. heading marker + the word "section"      ("## Section A")
#  2. heading marker + a BARE letter            ("## A", "### C", "## A:") that IS the whole
#     heading, optionally followed by one `:` `.` or `-`. "## A note on scope" must not match,
#     or a seat's ordinary prose heading would satisfy a section it never wrote.
#  3. no heading marker, word "section" required ("Section A", "**Section A**"); a bare letter
#     here would match the first letter of ordinary prose.
SECTION_RE = re.compile(
    r"^\s*#{1,4}\s*\**\s*section\s+([abc])\b"
    r"|^\s*#{1,4}\s*\**\s*([abc])(?=[:.\-]?\s*$)"
    r"|^\s*\**\s*section\s+([abc])\b",
    re.I | re.M)
NUMBERED_RE = re.compile(r"^\s{0,3}(?:\d{1,2}[.)]|[-*+])\s+\S", re.M)


def section_letter(m):
    return next(g for g in m.groups() if g is not None)


def compliance(content, shape, cap):
    """Count what the seat returned against the shape it was asked for. Two question counts are
    reported because either heuristic alone can be wrong on a seat that writes prose; two numbers
    that disagree mean: read the output. Never raises."""
    found = sorted({section_letter(m).upper() for m in SECTION_RE.finditer(content)})
    out = {"sections_found": found, "shape": shape, "cap": cap}
    if shape != "questions":
        out["sections_expected"] = []
        out["verdict"] = "n/a (not a questions round)"
        return out
    out["sections_expected"] = ["A", "B", "C"]
    out["sections_missing"] = [s for s in ("A", "B", "C") if s not in found]

    marks = list(SECTION_RE.finditer(content))
    body = content
    a = next((m for m in marks if section_letter(m).upper() == "A"), None)
    if a:
        after = [m for m in marks if m.start() > a.start()]
        body = content[a.end():after[0].start()] if after else content[a.end():]
        out["counted_in"] = "section A"
    else:
        out["counted_in"] = "whole output (section A not marked)"

    enumerated = len(NUMBERED_RE.findall(body))
    interrogative = len([ln for ln in body.splitlines() if ln.strip().endswith("?")])
    out["questions_enumerated"] = enumerated
    out["questions_interrogative"] = interrogative

    n = max(enumerated, interrogative)
    if cap and n > cap:
        out["verdict"] = f"OVER cap ({n} > {cap})"
    elif cap and n < cap * 0.5:
        out["verdict"] = (f"UNDER cap ({n} of {cap}): a seat that self-caps reads as a seat "
                          f"with little to say. Check the output before believing it.")
    else:
        out["verdict"] = "within cap"
    if out["sections_missing"]:
        out["verdict"] += f" | sections missing: {','.join(out['sections_missing'])}"
    return out


# --------------------------------------------------------------------------- output

def slug(seat):
    return re.sub(r"[^a-z0-9]+", "-", seat.lower()).strip("-")


def seat_markdown(r):
    """The exact text written for one seat. The model's text is byte-identical below the comment."""
    return (f"<!-- seat: {r['seat']} | model: {r['model']} | provider: {r['provider']} | "
            f"tokens in/out: {r['prompt_tokens']}/{r['completion_tokens']} | "
            f"{r['seconds']}s | finish: {r['finish_reason']} -->\n\n{r['content']}\n")


def synthesis_markdown(synth_model, raws, r):
    return (f"<!-- synthesised by: {synth_model} | sources: "
            f"{', '.join(p.name for p in raws)} | {r['seconds']}s -->\n\n{r['content']}\n")


# --------------------------------------------------------------------------- run

def resolve_keys(args, seats, order):
    if args.only or args.seats:
        keys = []
        for raw in (args.only or args.seats).split(","):
            k = _norm(raw)
            if k not in seats:
                sys.exit(f"no seat named {raw!r} on this panel. Panel has: "
                         f"{[seats[o]['seat'] for o in order]}")
            keys.append(k)
        return keys
    return list(order)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--brief", required=True, help="the document the panel reviews, as markdown")
    ap.add_argument("--outdir", required=True, help="where every raw output and the logs are written")
    ap.add_argument("--panel", default="general", help="a shipped panel name or a path to your own .toml")
    ap.add_argument("--providers", help="providers .toml; default is the shipped file, see config/")
    ap.add_argument("--seats", help="comma-separated seats for this run; default is the whole panel")
    ap.add_argument("--only", help="comma-separated seats, to re-run just those after a failure")
    ap.add_argument("--round-shape", choices=["questions", "verdict", "none"], default="none",
                    help="the round-shape instruction appended to each SYSTEM prompt")
    ap.add_argument("--max-questions", type=int, default=10, help="cap for a questions round")
    ap.add_argument("--synthesise", action="store_true",
                    help="synthesis pass over the seat outputs already in --outdir; skips the panel")
    ap.add_argument("--synth-model", help="model for the synthesis pass; default is the panel's")
    ap.add_argument("--max-tokens", type=int, help="override every seat's max_tokens")
    ap.add_argument("--timeout", type=int, help="override every seat's timeout in seconds")
    ap.add_argument("--max-cost", type=float, metavar="USD",
                    help="refuse to run when the estimated ceiling cost exceeds this")
    ap.add_argument("--allow-unpriced", action="store_true",
                    help="with --max-cost, run even when a seat's price is unknown")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the panel, size the brief, estimate the cost. Calls no model; may read "
                         "the provider's public price list.")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    providers = load_toml(find_providers(args.providers))
    if "providers" not in providers:
        sys.exit("providers file has no [providers.*] tables.")
    for pname, pv in providers["providers"].items():
        if "@" in urlparse(pv.get("base_url", "")).netloc:
            sys.exit(f"providers file: {pname} has credentials inside base_url. Keys belong in an "
                     f"environment variable named by key_env.")
    default_provider = providers.get("default", "openrouter")
    if default_provider not in providers["providers"]:
        sys.exit(f"providers file: default {default_provider!r} is not defined.")
    seats, order, synth = load_panel(find_panel(args.panel), providers, default_provider)
    shapes = load_shapes()

    brief_path = pathlib.Path(args.brief)
    if not brief_path.exists():
        sys.exit(f"brief not found: {brief_path}")
    brief = brief_path.read_text()
    outdir = pathlib.Path(args.outdir)

    if args.synthesise:
        return synthesise(args, synth, brief, outdir, providers)

    keys = resolve_keys(args, seats, order)
    shape_text = ""
    if args.round_shape != "none":
        shape_text = shapes[args.round_shape].replace("{N}", str(args.max_questions))

    resolved = {}
    for k in keys:
        s = seats[k]
        resolved[s["seat"]] = {**s, "max_tokens": args.max_tokens or s["max_tokens"],
                               "timeout": args.timeout or s["timeout"],
                               "system": s["system"] + (" " + shape_text if shape_text else "")}

    # ---- the estimate, printed by the code that will spend the money
    brief_tok = len(brief) // CHARS_PER_TOKEN
    print(f"[council] panel {args.panel}; brief {len(brief.encode()):,} bytes "
          f"(~{brief_tok:,} tokens); round shape {args.round_shape}"
          + (f", cap {args.max_questions}" if args.round_shape == "questions" else ""))
    est_in = est_out = est_cost = 0.0
    unpriced = []
    for name, c in resolved.items():
        sys_tok = len(c["system"]) // CHARS_PER_TOKEN
        px = price_for(c, providers)
        cost = ((brief_tok + sys_tok) * px[0] + c["max_tokens"] * px[1]) if px else None
        if cost is None:
            unpriced.append(name)
        else:
            est_cost += cost
        est_in += brief_tok + sys_tok
        est_out += c["max_tokens"]
        prov = providers["providers"][c["provider"]]
        ignored = (" reasoning ignored by provider" if c.get("reasoning")
                   and "reasoning" not in prov.get("body_fields", []) else "")
        print(f"[council]   {name:22} {c['provider']}:{c['model']:30} max_tokens={c['max_tokens']:<6} "
              f"timeout={c['timeout']:<5} status={c['status']}"
              + (f"  ~${cost:.2f}" if cost is not None else "  price unknown") + ignored)
    print(f"[council] estimate: ~{est_in:,.0f} prompt + up to {est_out:,.0f} completion tokens, "
          + (f"~${est_cost:.2f} at the ceiling" if est_cost else "cost unknown")
          + (f" ({len(unpriced)} seat(s) unpriced: {', '.join(unpriced)})" if unpriced and est_cost else "")
          + f"  ({len(resolved)} calls)")
    print("[council] The completion figure is a CEILING, not a forecast: cost lands lower whenever a "
          "seat answers in less than its budget.")

    used = {c["provider"] for c in resolved.values()}
    hosts = sorted({f"{urlparse(providers['providers'][p]['base_url']).hostname} ({p})" for p in used})
    print(f"[council] DATA: the brief and the seat prompts are sent to: {', '.join(hosts)}. "
          f"Do not include anything you would not send to those providers.")
    problems = key_problems(used, providers)
    for p in problems:
        print(f"[council] KEY MISSING  {p}")
    if not problems:
        print("[council] keys: present for every provider this run uses")

    if args.max_cost is not None:
        if unpriced and not args.allow_unpriced:
            sys.exit(f"[council] REFUSED: --max-cost is set but {len(unpriced)} seat(s) have no known "
                     f"price ({', '.join(unpriced)}). Pass --allow-unpriced to run anyway.")
        if est_cost > args.max_cost:
            sys.exit(f"[council] REFUSED: estimated ceiling ${est_cost:.2f} exceeds --max-cost "
                     f"${args.max_cost:.2f}. Lower max_tokens (--max-tokens), use fewer seats, or "
                     f"raise the cap.")

    if args.dry_run:
        print("[council] --dry-run: nothing called, nothing written.")
        return 0
    if problems:
        sys.exit("[council] REFUSED: a key is missing (above). Nothing was sent.")

    outdir.mkdir(parents=True, exist_ok=True)
    results = []

    def file_result(r):
        """Written the moment a seat returns, so an interrupt or a crash in another seat never
        loses replies that were already paid for."""
        if r["ok"]:
            r["compliance"] = compliance(r["content"], args.round_shape, args.max_questions)
            path = outdir / f"{slug(r['seat'])}.md"
            path.write_text(seat_markdown(r))
            print(f"[council] {r['seat']}: OK  {r['completion_tokens']} out tok, "
                  f"{r['seconds']}s, finish={r['finish_reason']} -> {path}", flush=True)
            if r["finish_reason"] == "length":
                print(f"[council]   WARNING: {r['seat']} was cut off at max_tokens, so its output "
                      f"may end mid-argument. Re-run it with --only and a larger --max-tokens "
                      f"before relying on it.", flush=True)
        else:
            print(f"[council] {r['seat']}: FAILED after {r['seconds']}s: {r['error']}", flush=True)

    with cf.ThreadPoolExecutor(max_workers=max(1, len(resolved))) as pool:
        futures = {pool.submit(call, c, c["system"], brief, providers, c["max_tokens"], c["timeout"]): n
                   for n, c in resolved.items()}
        for f in cf.as_completed(futures):
            try:
                r = f.result()
            except Exception as e:               # a defect in call() must not lose the others
                c = resolved[futures[f]]
                r = {"seat": futures[f], "model": c["model"], "provider": c["provider"], "ok": False,
                     "seconds": 0, "error": f"internal error: {type(e).__name__}: {e}"}
            results.append(r)
            file_result(r)
    seat_order = [seats[k]["seat"] for k in keys]
    results.sort(key=lambda r: seat_order.index(r["seat"]))

    ok = [r for r in results if r["ok"]]
    if ok and args.round_shape == "questions":
        print(f"\n[council] shape compliance, cap {args.max_questions}")
        print(f"[council] {'Seat':22} {'enum':>5} {'?':>5} {'sections':10} verdict")
        for r in ok:
            c = r["compliance"]
            print(f"[council] {r['seat']:22} {c['questions_enumerated']:>5} "
                  f"{c['questions_interrogative']:>5} {''.join(c['sections_found']) or '-':10} "
                  f"{c['verdict']}")

    strip = lambda c: {k: v for k, v in c.items() if k != "system"}
    (outdir / "panel-as-run.json").write_text(json.dumps({
        "version": __version__, "panel": args.panel, "brief": args.brief,
        "brief_bytes": len(brief.encode()), "round_shape": args.round_shape,
        "max_questions": args.max_questions if args.round_shape == "questions" else None,
        "seats": {n: strip(c) for n, c in resolved.items()},
        "system_prompt_chars": {n: len(c["system"]) for n, c in resolved.items()},
    }, indent=2) + "\n")
    log = outdir / "run-log.json"
    prior = json.loads(log.read_text()) if log.exists() else []
    prior.append({"brief": args.brief, "round_shape": args.round_shape,
                  "seats": {n: strip(c) for n, c in resolved.items()},
                  "results": [{k: v for k, v in r.items() if k != "content"} for r in results]})
    log.write_text(json.dumps(prior, indent=2) + "\n")

    failed = [r["seat"] for r in results if not r["ok"]]
    if failed:
        print(f"\n[council] {len(failed)} seat(s) FAILED: {failed}")
        print("[council] re-run just those, without re-running the panel:")
        print(f"[council]   council.py --brief {args.brief} --outdir {args.outdir} --panel {args.panel} "
              f"--round-shape {args.round_shape} --only {','.join(failed)!r} --timeout 1500")
        return 1
    print(f"\n[council] all {len(results)} seats returned. Log: {log}")
    return 0


def synthesise(args, synth, brief, outdir, providers):
    """Synthesis by a model over the seat outputs already on disk. The alternative, the session
    writing the synthesis itself, is the default and is not this path. Either is auditable only
    because the raw seat outputs stay untouched."""
    if not synth:
        sys.exit("this panel defines no [synthesiser]. Add one, or write the synthesis yourself.")
    raws = sorted(p for p in outdir.glob("*.md") if p.name != "synthesis.md")
    if not raws:
        sys.exit(f"no seat outputs in {outdir} to synthesise. Run the panel first.")
    if args.synth_model:
        synth = {**synth, "model": args.synth_model}
    parts = [brief, "\n\n---\n\n# The panel's raw outputs\n"]
    for p in raws:
        parts.append(f"\n\n## {p.stem}\n\n{p.read_text()}")
    payload = "".join(parts)
    max_tokens = args.max_tokens or synth["max_tokens"]
    print(f"[council] synthesising {len(raws)} seat output(s) with {synth['provider']}:{synth['model']} "
          f"({len(payload.encode()):,} bytes in)")
    px = price_for(synth, providers)
    cost = ((len(payload) + len(synth["system"])) // CHARS_PER_TOKEN * px[0] + max_tokens * px[1]) if px else None
    print(f"[council] estimate: ~{(len(payload) + len(synth['system'])) // CHARS_PER_TOKEN:,} prompt + up to "
          f"{max_tokens:,} completion tokens, " + (f"~${cost:.2f} at the ceiling" if cost is not None
                                                   else "cost unknown"))
    host = urlparse(providers["providers"][synth["provider"]]["base_url"]).hostname
    print(f"[council] DATA: the brief and the seat outputs are sent to: {host} ({synth['provider']}).")
    problems = key_problems({synth["provider"]}, providers)
    for p in problems:
        print(f"[council] KEY MISSING  {p}")
    if args.max_cost is not None:
        if cost is None and not args.allow_unpriced:
            sys.exit("[council] REFUSED: --max-cost is set but the synthesiser's price is unknown. "
                     "Pass --allow-unpriced to run anyway.")
        if cost is not None and cost > args.max_cost:
            sys.exit(f"[council] REFUSED: estimated ceiling ${cost:.2f} exceeds --max-cost "
                     f"${args.max_cost:.2f}.")
    if args.dry_run:
        print("[council] --dry-run: nothing called, nothing written.")
        return 0
    if problems:
        sys.exit("[council] REFUSED: a key is missing (above). Nothing was sent.")
    r = call(synth, synth["system"], payload, providers, max_tokens, args.timeout or synth["timeout"])
    if not r["ok"]:
        print(f"[council] Synthesiser FAILED after {r['seconds']}s: {r['error']}")
        return 1
    out = outdir / "synthesis.md"
    out.write_text(synthesis_markdown(synth["model"], raws, r))
    print(f"[council] synthesis -> {out}  ({r['completion_tokens']} out tok, {r['seconds']}s)")
    print("[council] the raw seat outputs are untouched, which is the only check on this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
