# The method behind the two-round review

Why [SKILL.md](../SKILL.md) runs a review the way it does, and the mechanics that bite. SKILL.md
is the procedure; this is the reasoning. Read it before assembling a brief or deciding between one
round and two.

## The shape is a procurement process

It is an RFI followed by an RFP, and the same logic sits behind an RFQ. You publish the information,
the vendors tell you what they still need to know, you answer every vendor in one addendum, and only
then do they bid. Each rule in the method is a rule of good procurement carried over:

| Procurement rule | What it becomes here |
|---|---|
| Bidders see only the tender pack | The panel sees only the brief. Nothing the brief omits can be recovered by a reviewer |
| Clarification questions come before bids | Round 1 is a questions round: no verdict, no issues list |
| One addendum goes to every bidder | One shared answers document, attributed by seat and question number, so each seat sees what the others asked and there is one artefact to audit |
| Unanswered questions are declared, not ignored | A mandatory section lists what you deliberately did not answer, with reasons |
| Bidders are independent | Different vendors' models, so the panel is not one model's view repeated |
| The evaluation is auditable | Raw outputs are filed unedited beside the synthesis |
| Spend needs approval | The runner prices each round and the skill stops for a yes |

A one-round review skips the middle step. It buys a confident verdict from a panel that never said
what it could not see.

## When the second round earns its cost

Run two rounds when **being wrong is expensive and the reviewers cannot see the system**. Run one
when the material is self-contained and the stakes are ordinary.

The tell that you needed two: a one-round panel produced confident findings about things it had no
way to check.

## Frame the charge, not the document

**A charge beats "what do you think".** Say what specifically changed and why they are being asked,
in the reviewers' own terms. One sentence that says a decision ratified earlier has materially
changed, with the before and after, focuses a panel more than a long document beneath it.

If you are verifying prior conditions, **enumerate them and ask for each to be ruled on
separately**: "verify each was folded in, and say which are satisfied, weakened or lost" beats a
general critique.

A deliberately negative primary question outperforms an open one when the subject is something the
owner already likes. "Which of these parts is NOT worth its standing cost" returns usable material;
"is this good?" returns yes.

## Build the brief

- **Send the source, never a summary.** A summary drops the numbers, and the panel then reviews
  assertions instead of evidence.
- **Trim by heading anchor, in a script, and fail loudly if the anchor moved.** A silent no-op trim
  sends everything and nothing notices. The script is the auditable record of what was and was not
  sent, so keep it beside the run's artefacts.
- **Add an orientation note and a lexicon.** Invented vocabulary burns a reviewer's findings on
  vocabulary. Say what the system is, who runs it, and what each coined term means.
- **State the constraints they must design within** (budget, headcount, overhead ceilings) or you
  will get recommendations that propose around them.

## What round 1 asks for

The runner's `questions` round shape asks for exactly three things:

1. **The questions they need answered**, each with one line on **what turns on the answer**: which
   way their judgement moves. That line is the triage key for the answering step, and it is the
   reviewer's own filter rather than yours.
2. **What they cannot assess at all** without access they do not have, named explicitly.
3. **The three things they would most want to be wrong about.** It pulls toward compressed
   verdicts, but produced some of the sharpest material in the rounds that tried it, so it is kept
   as a deliberate trade.

**Persona prompts must not hardcode critique behaviour.** A persona that says "identify the 3 to 5
most important issues only" fights a questions round and wins. The shipped personas carry no issue
count, question count or round instruction. If you add a seat with a cap baked into its persona,
this failure returns. The tests check the shipped panels for it.

Check each returned output against the shape asked for rather than assuming compliance. The runner
counts; deciding whether a thin section is thin or truncated is your judgement.

## Answer with measurement

**Re-measure; never quote a figure from the document under review.** Re-running a figure on the
current data turns a quoted claim into a tested one. Where the re-measurement disagrees, give the
new number and say so.

**Answer where the reviewer's own "what turns on it" line shows the verdict moves.** Four seats
produce roughly a hundred questions. Answering all of them is several sessions; answering none
wastes the round.

**A section of what you deliberately did not answer, with reasons, is mandatory**, and say which
unanswered question is the most valuable, so the panel can weight its verdict. An unanswered
question marked as unanswered is worth more than a confident guess.

**Put your own failures in the answers.** If the system broke while you were reviewing it, that is
evidence about the design, and withholding it is the failure the review exists to find.

## Round 2's structure

Brief 2 is brief 1 plus the shared answers. Structure the ask so targeted verification and open
critique do not crowd each other out: named sections for the specific verifications, one item at a
time; then an open-critique section with the issue cap explicitly lifted; then a one-line overall
verdict. Each recommendation comes back as a decision record (Context, Candidates considered,
Decision, Rationale, Cost) so alternatives survive.

Relay the panel's output verbatim. **If you synthesise it yourself you are not a clean room**: you
have read the material and formed views. Filing the raw outputs is what makes your synthesis
auditable. A model synthesis has not read the material, but cannot check a claim against your
sources either; neither route is cleaner in every respect.

## Mechanics that will bite

**Reasoning models return empty content when the reasoning budget eats the completion budget.**
OpenRouter documents it. Raising `max_tokens` makes it worse, because it gives the model more room
to think and none to answer. Cap the share instead (`reasoning = { effort = "low" }`) and verify the
parameter reaches the model before spending on a real run: a cheap prompt at `effort = "low"`
versus `"none"` should show different reasoning-token counts.

**Seats do not share a working configuration.** Pin each seat to what demonstrably worked for it
rather than one setting for all. The `status` field on a seat records whether that pairing has
returned. A model swap without evidence is a seat that may never answer.

**An empty return is indistinguishable from a refusal** unless `finish_reason` and the message keys
are recorded. The runner logs both, always.

**Every raw output is written to disk as it arrives**, and one seat re-runs with `--only`.

**Check your balance before each round, not once at the start.** Round 2's input is materially
larger than round 1's, and per-seat output prices vary by an order of magnitude.

## What this is not

It is not a second opinion from the same model. Model diversity (several vendors, one role each)
and role diversity (one model playing several roles) are different things. A review that needs both
should say so. And it is not a substitute for checking facts: the panel can only be as good as the
brief.
