# Neutrino Linguist / GitHub highlighting assets ()

Static-highlighting assets for `.neu`, **packaged from the one generated grammar** — there
is no second, hand-maintained grammar here. Both files are generated/copied from the
compiler's output by `scripts/generators/generate_linguist_assets.py`:

| File | What | Source |
| --- | --- | --- |
| [`neutrino.tmLanguage.json`](neutrino.tmLanguage.json) | the TextMate grammar | a byte copy of [`../docs/neutrino.tmLanguage.json`](../docs/neutrino.tmLanguage.json) (generated from the compiler metadata, ) |
| [`languages.yml`](languages.yml) | the Linguist language entry | derived from `../docs/language-metadata.json` (`.neu` extension) + the grammar (`source.neutrino` scope) |

Regenerate both with `make linguist`. The fast-tier check `[fast/22]`
(`scripts/generators/generate_linguist_assets.py --check`, also a labeled CTest) fails CI if the
packaged grammar drifts from the generated one or `languages.yml` goes stale — so the
package can never diverge from the compiler.

## How consumers use these

- **VS Code / any TextMate host** — point the grammar contribution at
  `neutrino.tmLanguage.json` (scope `source.neutrino`, extension `.neu`). This works today;
  it does not depend on Linguist.
- **This repo on GitHub** — the root [`.gitattributes`](../.gitattributes) maps `*.neu` to
  `Neutrino` and marks the generated grammar files `linguist-generated`. GitHub applies the
  attribute overrides today; syntax **highlighting** on github.com, however, only renders
  once the `Neutrino` language exists in upstream Linguist (below).
- **A local Linguist-compatible tool** — merge the `languages.yml` entry into a local
  `github-linguist` checkout's `lib/linguist/languages.yml` and vendor
  `neutrino.tmLanguage.json`, then run Linguist locally to highlight/classify `.neu`.

## Upstream `github-linguist` — tracked follow-up (NOT an M5 blocker)

GitHub-web highlighting of `.neu` requires the `Neutrino` language to be merged into
[github-linguist](https://github.com/github-linguist/linguist). That is deliberately **out
of scope for M5 completion** (guardrail): we ship the exact assets the upstream PR needs and
track the merge separately.

The upstream PR would:
1. add the `Neutrino:` entry from `languages.yml` to `lib/linguist/languages.yml` (with a
   maintainer-assigned, globally-unique `language_id` — the `language_id` here is
   **provisional** (`999900001`) and MUST be replaced upstream);
2. vendor `neutrino.tmLanguage.json` as the grammar submodule/source for `source.neutrino`;
3. add grammar/sample tests.

**External usage-threshold risk.** Linguist requires a language to be **in real-world use**
before acceptance — historically on the order of **hundreds of public repositories / files**
using the extension. Until `.neu` clears that bar, an upstream PR will be declined regardless
of asset quality, so github.com highlighting remains blocked on adoption, not on this work.
This is why upstream acceptance is explicitly not an M5 criterion; the assets are ready to
submit the moment the threshold is met.
