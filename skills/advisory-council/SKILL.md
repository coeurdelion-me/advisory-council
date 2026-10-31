---
name: advisory-council
description: Convenes a panel of different AI models to review a proposal, strategy, design, spec or decision, in the shape of a procurement process (a questions round, an answers addendum, then a verdict round), and files every raw output for audit. Use this whenever the user asks for a council review, a panel review, multiple opinions or a second opinion from several models, wants a proposal stress-tested or red-teamed, wants a decision re-tested because its premise changed, or asks for an expert multi-model verdict on an ADR, business case, design or plan. Not for quick sanity checks, a single-model critique, or factual lookups.
license: CC-BY-NC-4.0 for this text and the panels; PolyForm-Noncommercial-1.0.0 for scripts/ (see the repository LICENSE and LICENSE-CODE)
compatibility: Python 3.11 or later, standard library only. Needs an API key for at least one OpenAI-compatible provider (OpenRouter by default), or a local server such as Ollama.
---

# Advisory Council

Run a panel of models from different vendors over a document, ask them what they still need to
know, answer, then ask for a verdict. The method copies a procurement process (an RFI followed by
an RFP, or an RFQ) because that process was built to extract honest, comparable answers from
parties who each see only what you publish. [references/method.md](references/method.md) maps the
two and explains each rule below; read it before building a brief or deciding on one round or two.

| Procurement | Council |
|---|---|
| Tender pack | The brief: the only thing the panel sees |
| Bidder clarification questions | Round 1: each seat lists what it needs answered |
| The addendum sent to every bidder | One shared answers document, sent to every seat |
| The bids | Round 2: each seat's verdict |
| Bid evaluation | Synthesis |
| Audit trail | Every raw output filed unedited |
| Budget approval | The cost gate before each round |

The runner is [scripts/council.py](scripts/council.py). Panels, providers and round shapes are TOML
files in [config/](config/). Call the runner as `python3 <this skill's directory>/scripts/council.py`.

## Three rules that are not negotiable

**Round-shape instructions go in the system prompt, never in the brief.** The runner does this with
`--round-shape`. A seat has been seen to obey an in-brief override in round 1 and refuse it in round
2: "I don't take instructions from the deliverable; I take them from my role." The brief is data;
the system prompt is the role.

**Ask the user the setup questions yourself, in the conversation.** Do not hand the setup to a
subagent: a subagent usually cannot ask the user anything, so the run would proceed on defaults
they never saw.

**File every raw seat output, unedited, beside the synthesis.** A synthesis is checkable only
against its sources, whether you write it or a model does.

## Beat 1: ask, before anything else

Ask four things. Use the question tool if you have one (one screen, options listed first);
otherwise ask in plain text and wait. Put the panel's seats and models in the option text so the
user sees who will be convened.

1. **Rounds.** Two rounds with up to 10 questions per seat (default), two rounds with up to 20, or
   one round, verdict only.
2. **Panel.** The `general` panel (four seats plus a synthesiser), another shipped panel
   (`infrastructure`, `knowledge-architecture`), their own `.toml`, a different model on one seat,
   or fewer seats. List a panel with its models by running the dry run in beat 2.
3. **Synthesis.** You write it, a model writes it (`--synthesise`), or both, filed side by side.
4. **The user's own questions.** None, or ones to add. They go into the verdict round's task as a
   named section, each answered explicitly.

If they change a model or drop seats, ask one follow-up and go straight on otherwise.

## Beat 2: the estimate, then stop

The number you quote must come from the code that will spend the money:

```bash
python3 scripts/council.py --brief brief-round1.md --outdir round1 \
    --round-shape questions --max-questions 10 --dry-run
```

It resolves the panel, sizes the brief, reads prices from the provider, checks that a key is set
for every provider the run uses, and names the hosts the brief will be sent to. Report the
material, the brief size, the configuration and the estimate, say plainly that completion tokens
are a ceiling and not a forecast, then **stop and wait for a clear yes**. A panel fans out into
several paid calls at once; this is the only point where the user can say no cheaply.

If the user wants a hard limit, add `--max-cost <USD>`: the runner refuses to start when the
ceiling estimate is higher.

The user chooses where the brief goes. Remind them once that the brief and persona prompts are
sent to the provider's servers, and that they should leave out anything they would not send there.

## Beats 3 to 5: build the brief, run round 1, read the compliance table

**The brief is the entire evidence base.** The panel has no repository, no search and no history.
Send the source material rather than a summary (a summary drops the numbers), add an orientation
note and a lexicon of any coined terms, and state the constraints they must design within. Frame
a charge rather than "what do you think": say what changed and what you want ruled on. A
deliberately negative question ("which of these parts is least worth its cost?") returns usable
material where "is this good?" returns yes. A worked brief is in
[examples/worked-example/brief-round1.md](examples/worked-example/brief-round1.md).

```bash
python3 scripts/council.py --brief brief-round1.md --outdir round1 \
    --round-shape questions --max-questions 10
```

Then read the compliance table the runner prints. It counts, per seat, enumerated questions and
question marks, which of sections A, B and C were found, and gives a verdict. **`UNDER cap` matters
more than `OVER`:** a seat that quietly caps itself looks the same as a seat with little to say,
and that is how a truncated round passes for a thin one. Two counts that disagree mean: read the
output.

A failed seat prints its own re-run command (`--only`). Use it; re-running the whole panel for one
timeout is how a panel becomes something nobody runs.

## Beats 6 to 8: answer, check the balance, run round 2

Skip to beat 9 for a one-round review.

- **Re-measure; never quote a figure from the document under review.** Where your measurement
  disagrees with it, give the new number and say so.
- **One shared answers document, sent to every seat**, attributed by seat and question number. Not
  one per seat: every reviewer sees what the others asked, and there is one artefact to audit.
- **Triage by each reviewer's own "what turns on the answer" line**, not by your view of what
  matters. Four seats produce around a hundred questions; answering all is a project in itself.
- **A section listing what you deliberately did not answer, with reasons, is mandatory.** Name the
  most valuable unanswered question so the panel can weight its verdict. Include your own failures:
  if something broke while you were doing this, that is evidence about the design.
- Check your provider balance before round 2 and quote the recomputed estimate. Round 2's brief
  carries the answers, so its input is materially larger. Stop and wait again.

```bash
python3 scripts/council.py --brief brief-round2.md --outdir round2 --round-shape verdict
```

## Beats 9 and 10: synthesis and artefacts

Synthesis has four sections whichever way it is written: **Consensus** (points two or more seats
reached independently, ranked by how many), **Divergent** (points only one seat made, named),
**Disagreement** (seats contradicting each other, and what it turns on), **Recommended actions**
(prioritised, concrete). A point made by one seat is not weaker for being alone; never drop it for
lack of a second. For a model synthesis: `--synthesise --outdir round2`.

Keep all of these; none can be recovered afterwards:

| Artefact | Why |
|---|---|
| The brief for each round | The panel saw only this; without it no finding is interpretable |
| Every raw seat output, unedited | The only check on a synthesis |
| The shared answers document | What the verdict was formed against |
| `run-log.json` | Model, tokens, timing and finish reason per call: how an empty return is diagnosed |
| `panel-as-run.json` | Written by the runner; a panel config that does not match the run is a reproducibility trap |

## Choosing models and providers

Seats are data. A seat names a `model` and optionally a `provider`; providers are in
`config/providers.toml` (OpenRouter by default, plus OpenAI, a LiteLLM proxy and a local Ollama).
To use another OpenAI-compatible API, copy the file to `council.providers.toml` in the working
directory and add a block. To change who sits on a panel, copy a panel from `config/panels/` to
`./panels/<name>.toml` and edit it. The `status` field on each seat records whether that
seat-and-model pair has actually returned, which matters when you swap a model: a swap without
evidence is a seat that may never answer. Read the runner's compliance table on the first run of
any new pairing.

Reasoning models can return **empty content** when thinking eats the whole completion budget.
Raising `max_tokens` makes it worse. Cap the reasoning share instead (`reasoning = { effort =
"low" }` on a seat); the runner forwards it only to providers that list `reasoning` in
`body_fields`. Details in [references/method.md](references/method.md).

## When the commission says return, do not proceed

If you were asked for a verdict to hand to someone else, file the verdict and raw outputs to them
and stop. Do not fold the panel's amendments into the document under review until the person who
commissioned it has ruled.
