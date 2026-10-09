# German+ Curriculum Data

Public content repository for the German+ Android app.
**PR → CI validation → maintainer review → merge = live on users' phones.**

The app downloads this repo raw from `main` and layers it over the content
bundled in the APK. Nothing here is ever stored in Firebase.

## Layout (flat — paths in `manifest.json` are relative to repo root)

```
manifest.json                  ← entry point: chapters[] + versions + remoteBaseUrl
chapter_01/
  index.json                   ← chapter meta + section list (each with version)
  s1_begruessung.json          ← one file per section (module bundle)
  s2_satzbau.json
  s3_aussprache.json
  vocab.json                   ← full Stimmung-style word cards
  exam.json                    ← Goethe-style questions + saveable concepts
chapter_02/
  index.json
  s1_zeit.json
  s2_essen.json
  s3_zahlen.json
  vocab.json
  exam.json
tools/validate.py              ← schema validator (CI runs this)
.github/workflows/validate.yml ← PR gate
```

## The change contract (cheap sync)

The app downloads **only what changed**:

- Bump `manifest.contentVersion` when anything changes.
- Bump a chapter's `version` when its `index.json` changes.
- Bump a section's `version` when the section file changes.
- `vocab.json` / `exam.json` are versioned with the chapter — bump the
  chapter `version` when you edit them.

Forgetting a version bump = users don't get the update. The validator
warns when files are newer than declared versions (best-effort check).

## Schema rules enforced by CI

- Every file needs `schemaVersion` (currently `1`).
- Section file `id` must equal its `id` in `index.json`.
- `practice[].correctIndex` and `exam.questions[].correctIndex` must be
  within `options` range.
- `writing.solutionWords` ⊆ `writing.wordPool` (and grammar builder).
- Nouns need `article` + `gender`; every card needs `ipa` and
  `meaningsEnglish`; word ids unique per chapter.
- Exam `concept` blocks need `title` + `rule`.

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
- Sections target ~6–8 minutes: 3–4 core pages, 1 grammar module
  (optional), 1–2 patterns, optional writing module, 2–3 practice
  questions with `explanationEnglish`.
- Exam questions: 4–6 per section-set, each with a `concept` block the
  learner can save to their concept book.
