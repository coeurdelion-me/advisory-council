# Security

## What the code does

`council.py` reads a brief you point it at, sends it with each seat's persona to the provider API
endpoints named in your providers file, and writes the replies to the output directory you name.
It reads API keys from environment variables only, never from a file, and writes no key to any
output or log. It contacts only hosts in the providers file, plus the OpenRouter public
`/models` list for prices when a provider sets `pricing = "openrouter"`.

## What to be careful of

- **Your brief leaves your machine.** It goes to every provider the run uses. The dry run prints
  those hosts. Do not put in anything you are not allowed to send there.
- **The brief is untrusted data to the models, and model output is untrusted data to you.** A
  seat's reply is text. Do not execute it, and be wary of anything it asks you to fetch or run.
- **Spend is yours.** `--dry-run` prices a run, and `--max-cost` refuses to start above a ceiling.
  The ceiling counts every seat running to its full `max_tokens`.
- **Providers can see prompts under their own terms.** Check your provider's data-retention and
  training settings before sending anything sensitive.

## Reporting a problem

Open a GitHub issue for ordinary bugs. For anything that could expose a key or a brief, use the
repository's private vulnerability reporting under the Security tab, not a public issue.
