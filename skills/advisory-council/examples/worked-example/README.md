# Worked example

A complete two-round review, run for real on 31 October 2026 through OpenRouter on the `general`
panel. **The subject is invented**: Larkspur Cycles does not exist and every figure in the brief and
the answers is made up, so nothing here describes a real business.

| File | What it is |
|---|---|
| [brief-round1.md](brief-round1.md) | The tender pack: orientation, lexicon, the charge, constraints |
| [round1/](round1/) | Each seat's questions, plus `panel-as-run.json` and `run-log.json` |
| [answers.md](answers.md) | The one shared addendum sent to every seat, including what was deliberately not answered |
| [brief-round2.md](brief-round2.md) | Brief 1 plus the answers plus the verdict ask |
| [round2/](round2/) | Each seat's verdict, and `synthesis.md` |

Things worth noticing:

- **Round 1 ran with `--max-tokens 4000` and `--max-questions 5`** to keep the cost of this example
  low (about 4,700 tokens in and 7,700 out). Round 2 ran with `--max-tokens 6000`.
- **Two seats in round 2 hit that cap and stop mid-argument** (`finish_reason` is `length` for
  Strategist and The Client in `round2/run-log.json`). They are left as they came back, because the
  raw outputs are filed unedited. The runner now prints a warning when this happens; in a real
  review you would re-run those seats with `--only` and a larger `--max-tokens`.
- **The compliance table flagged the Strategist at 8 enumerated items against a cap of 5.** That is
  the heuristic counting sub-bullets; the two counts disagreeing is the cue to read the output,
  which is the point of printing both.
- The only edit to the logs is that the brief's file path was made relative.
