# German+ Curriculum Data

Public content repository for the German+ Android app.
**PR → CI validation → maintainer review → merge = live on users' phones.**

The app downloads this repo raw from `main` and layers it over the content
bundled in the APK. Nothing here is ever stored in Firebase.

## Layout (flat — paths in `manifest.json` are relative to repo root)

```
manifest.json                  entry point: chapters[] + versions + remoteBaseUrl
chapter_01/
  index.json                   chapter meta + section list (each with version)
  s1_begruessung.json          one file per section = one ordered blocks[]
  s2_satzbau.json
  s3_aussprache.json
  vocab.json                   full Stimmung-style word cards
  exam.json                    Goethe-style blocks[] + saveable concepts
chapter_02/
  index.json
  s1_zeit.json
  s2_essen.json
  s3_zahlen.json
  vocab.json
  exam.json
tools/validate.py              schema validator (CI runs this)
.github/workflows/validate.yml PR gate
```

## The schema in one screen

A section and an exam are the same thing: **one ordered array of blocks**.
The array order *is* the screen order — move a row, the lesson moves.

```json
{
  "schemaVersion": 2,
  "id": "s1_zeit",
  "title": "Die Uhrzeit",
  "blocks": [
    { "type": "LESSON_PAGE", "variant": "DIALOGUE",   "id": "s1p1", "turns": [ … ] },
    { "type": "NOTE",        "variant": "CULTURE",    "id": "s1_n1", "title": "Wie spät ist es?" },
    { "type": "NOTE",        "variant": "MISTAKE",    "id": "s1_n2", "title": "halb neun ≠ 9:30" },
    { "type": "EXERCISE",    "variant": "REORDER",    "id": "s1_e1", "points": 3, "prompt": "…" },
    { "type": "EXERCISE",    "variant": "FILL_BLANK", "id": "s1_e2", "points": 3, "prompt": "…" },
    { "type": "SUMMARY",     "variant": "RECAP",      "id": "s1_sum", "bullets": [ … ] }
  ]
}
```

Three things fall out of that array:

- **Order is yours.** Swap the two exercises and the lesson reorders with no
  code change.
- **A family may repeat.** Two `NOTE` blocks = two callout pages. Nothing in
  the app knows how many there should be.
- **Every block needs a unique `id`** inside its file — the app keys the
  learner's per-block answer state on it.

### `type` picks the renderer. `variant` only styles it.

That split is the whole design, so it is worth being exact about:

| | `type` (family) | `variant` (flavour) |
|---|---|---|
| Chooses | The renderer | Styling + which payload fields are read |
| Unknown value | **CI error** — needs a renderer and a release | **CI warning** — renders with the family default |
| Adding one | Schema change + app release | **JSON edit only, live instantly** |

| Family | Variants | What it needs |
|---|---|---|
| `NOTE` | `TIP` `USAGE` `CULTURE` `MISTAKE` | `title`, `bodyEnglish` (optional `bodyGerman`) |
| `LESSON_PAGE` | `DIALOGUE` `GRAMMAR` `VOCAB` `PRONUNCIATION` `READING` `ROLEPLAY` | `headline` + `bodyEnglish`/`bodyGerman`; or `turns: [{speaker, german, english}]` |
| `EXAMPLES` | `PHRASE_LIST` `EXAMPLE_BOX` | `items: [{german, english}]` |
| `GRAMMAR` | `RULE` | `ruleHeadline`, `explanationEnglish`, optional `englishBridge`, optional `builder` |
| `PATTERN` | `FORMULA` | `title`, `formula`, `examples` |
| `BREAKDOWN` | `WORD_BY_WORD` | `sentenceGerman`, `tokens: [{token, english}]` |
| `VOCAB` | `CARD_SET` | `wordIds` (must exist in this chapter's `vocab.json`) or inline `words` |
| `EXERCISE` | `MULTIPLE_CHOICE` `FILL_BLANK` `MATCH` `REORDER` | `points` (positive), `prompt`, plus the payload below |
| `WRITING` | `WORD_POOL` | `promptEnglish`, `solutionWords` ⊆ `wordPool` |
| `SUMMARY` | `RECAP` | `bullets` |

### Exercise payloads and how they score

Each exercise declares `points`. Where a block holds several items the points
are shared evenly, so a ten-pair match outweighs a single check.

| `variant` | Reads | Scoring |
|---|---|---|
| `MULTIPLE_CHOICE` | `options`, `correctIndex` | all-or-nothing |
| `FILL_BLANK` | `items: [{sentence, answers, hint}]` — `sentence` must contain a `___` gap | `points × correct / items` |
| `MATCH` | `pairs: [{german, english}]` — German sides must be distinct | `points × correct / pairs` |
| `REORDER` | `builder: {fixedPrefix?, solutionWords, wordPool}` | all-or-nothing, once solved |

A `concept: {title, rule, exampleGerman?, exampleEnglish?}` can ride on **any**
variant — that is what "Save this concept" in the exam reads.

## The change contract (cheap sync)

The app downloads **only what changed**:

- Bump `manifest.contentVersion` when anything changes.
- Bump a chapter's `version` when its `index.json` changes.
- Bump a section's `version` when the section file changes.
- `vocab.json` / `exam.json` are versioned with the chapter — bump the
  chapter `version` when you edit them.

Forgetting a version bump = users don't get the update.

### schemaVersion

Every file carries `schemaVersion`. Sections, indexes, exams and the manifest
must be `2`. `vocab.json` is exempt: its format did not change, so it stays at
`1` and only has to be no newer than the app understands.

A file *newer* than the app is skipped rather than fatal — that is what makes
OTA safe. Inside a file, a block `type` the app has never seen renders as
nothing instead of failing the lesson.

## Schema rules enforced by CI

- Every file carries a `schemaVersion`; sections/indexes/exams/manifest = `2`.
- `type` must be one of the ten families. Unknown = build fails.
- `variant` should be one of the listed flavours. Unknown = warning only.
- Block `id`s must be non-empty and unique within the file.
- `EXERCISE` must carry a positive integer `points`.
- Per-variant payload must be present and well-formed (`correctIndex` in
  range, `___` gap in every fill-blank sentence, `solutionWords ⊆ wordPool`,
  …).
- `BREAKDOWN` gloss tokens must actually occur in the sentence being glossed.
- `VOCAB.wordIds` must resolve against the chapter's `vocab.json`.
- Section `id` must equal its `id` in `index.json`.
- Nouns need `article` + `gender`; every vocab card needs `ipa` and
  `meaningsEnglish`; word ids unique per chapter.
- Exam `concept` blocks need `title` + `rule`; at least one exam exercise
  should carry one, or nothing can reach the concept book.

A section file still carrying the v1 slots (`corePages`, `grammar`,
`patterns`, `writing`, `practice`) fails outright.

## Local validation

```bash
python3 tools/validate.py --root .
```

## Authoring workflow

1. Branch off `main`: `git checkout -b content/chapter-03-s1`
2. Copy `chapter_01/` as the structural template.
3. Edit JSON, run `validate.py` locally.
4. Open a PR — CI validates, maintainer reviews, merge to publish.

## Content style guide

- English bridges first (learner explains in plain English, then German).
- Every example German sentence gets an English translation.
- Sections target ~6–8 minutes. Don't force a fixed block count — use the
  family that fits. A lesson that needs three culture notes and no grammar
  module is a valid lesson.
- Put a `NOTE`/`MISTAKE` where the mistake belongs, not buried inside a
  grammar explanation.
- End with a `SUMMARY`/`RECAP` so the learner leaves with a checklist.
- Exam exercises: 4–6 per chapter, mixing variants where it helps, each with
  a `concept` block the learner can save to their concept book.
