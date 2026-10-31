# Advisory Council

Convene a panel of different AI models to review a proposal, design or decision. It runs in two
rounds, like a procurement process, and files every raw answer. Works with OpenRouter by default
and any OpenAI-compatible API. A Claude Code plugin, a plain Agent Skills folder, and a
command-line tool.

## Why it is shaped like a procurement process

A buyer who wants honest, comparable answers from several suppliers does not ask them "what do you
think?". They publish a tender pack, collect the suppliers' clarification questions, answer them
all in one addendum that every supplier receives, and only then ask for bids. A review by several
AI models has the same problem: reviewers see only what you hand them, and a verdict from a panel
that never said what it could not see is confident about things it could not check.

The council copies the process, step for step:

| Procurement | Council |
|---|---|
| Tender pack | **The brief**, the only thing the panel sees |
| Clarification questions from bidders | **Round 1**: each seat lists what it needs answered, what it cannot assess, and what it would most like to be wrong about |
| One addendum sent to every bidder | **One shared answers document** sent to every seat, so each sees what the others asked |
| The bids | **Round 2**: each seat's verdict, with recommendations as decision records |
| Bid evaluation | **Synthesis**: consensus, divergent points, disagreements, actions |
| Audit trail | **Every raw output filed unedited**, plus the brief, run log and the panel as it ran |
| Budget approval | **A priced dry run** before each round, and an optional hard cost ceiling |
| Independent bidders | **Different vendors' models**, one role per seat |

If the material is self-contained and the stakes are ordinary, run one round. Run two when being
wrong is expensive and the reviewers cannot see the system. The reasoning is in
[skills/advisory-council/references/method.md](skills/advisory-council/references/method.md).

## The panels

| Panel | Seats | For |
|---|---|---|
| `general` | Strategist, Operator, Devil's Advocate, The Client, plus a Synthesiser | A proposal, strategy or deliverable reviewed as a business document |
| `infrastructure` | Identity Architect, Offensive Security Engineer, Protocol Engineer, Reliability Engineer | An internet-exposure or architecture decision |
| `knowledge-architecture` | Knowledge Organisation Architect, Records and Metadata Standards Adviser, Schema and Migration Engineer, Agent Ergonomics Engineer | A classification, metadata or schema decision |

Panels are TOML files in [skills/advisory-council/config/panels/](skills/advisory-council/config/panels/).
Copy one to `./panels/mine.toml` to change who sits on it, or pass `--panel path/to/your.toml`.
A seat's `status` field says honestly whether that seat-and-model pair has returned a real answer in
the author's runs, so you can see which pairings are proven and which are not.

## Choosing your provider

The runner talks to any server that speaks the OpenAI `/chat/completions` format, one provider
profile per server:

| Provider | Setup |
|---|---|
| OpenRouter (default) | `export OPENROUTER_API_KEY=...` |
| OpenAI | `export OPENAI_API_KEY=...` and set `provider = "openai"` on a seat or `default = "openai"` |
| A LiteLLM proxy (reaches Anthropic, Gemini, Bedrock, Azure and more) | `export LITELLM_API_KEY=...`, base URL in the providers file |
| Ollama or another local server | No key. Point a profile at it |

Seats can use different providers in one panel. Add your own by copying
[providers.toml](skills/advisory-council/config/providers.toml) to `council.providers.toml`. Keys
come from environment variables only. The one provider-specific field, `reasoning`, is sent only to
providers that list it.

## Run it

With an assistant that supports skills (Claude Code, Claude Desktop, others), install the plugin or
the folder and say "run a council review of this proposal". The skill asks you the setup questions,
shows the cost, and waits for your yes before spending anything.

Without one, run the command line directly:

```bash
S=skills/advisory-council/scripts/council.py
python3 $S --brief brief-round1.md --outdir round1 --round-shape questions --dry-run   # prices it, calls nothing
python3 $S --brief brief-round1.md --outdir round1 --round-shape questions --max-cost 3
# answer the questions in brief-round2.md, then:
python3 $S --brief brief-round2.md --outdir round2 --round-shape verdict
python3 $S --brief brief-round2.md --outdir round2 --synthesise                         # optional model synthesis
```

A complete two-round review, with every artefact the runner and the method produce, is in
[examples/worked-example/](skills/advisory-council/examples/worked-example/). It is about an invented
business; the models' outputs are real.

## Cost and privacy

- **Your brief is sent to the provider's servers.** The dry run prints the hosts. Leave out anything
  you would not send there, and check the provider's data-retention terms.
- A round on the `general` panel is a handful of calls. The dry run reads live prices from OpenRouter
  and prints a ceiling; completion tokens are a ceiling, not a forecast.
- `--max-cost 3` refuses to start a run whose ceiling estimate exceeds three dollars.

---

## Install

**Claude Code plugin**

```
/plugin marketplace add coeurdelion-me/advisory-council
/plugin install advisory-council@advisory-council
```

**As a plain skill**: copy `skills/advisory-council/` into your assistant's skills folder (for
Claude Code, `~/.claude/skills/`), or use `advisory-council.zip` from the latest GitHub Release.

**Requirements**: Python 3.11 or later, nothing else to install. An API key for your provider, or a
local model server.

## Build and test

```bash
python3 tools/build.py        # validates the skill, writes dist/advisory-council.zip
python3 -m unittest discover -s tests -v
```

The tests run the real command against a fake local server, so the provider path is exercised
without spending anything.

## Also by the same author

[Strategy Advisor](https://github.com/coeurdelion-me/strategy-advisor): a skill that diagnoses a
business problem and picks the strategic framework that fits.

## Licence

Made by Coeur de Lion.

- The prompts, personas, skill text, documentation and examples are licensed
  [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): use, share and adapt them for any
  non-commercial purpose, crediting Coeur de Lion and saying what you changed. See [LICENSE](LICENSE).
- The Python code in `skills/advisory-council/scripts/`, `tests/` and `tools/` is licensed under the
  [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
  See [LICENSE-CODE](LICENSE-CODE).

For commercial use, open an issue to ask.
