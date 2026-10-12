#!/usr/bin/env python3
"""
GermanFlow curriculum validator — schema v2 (typed content blocks).

Run:  python3 validate.py [--root .]

A section (and an exam) is an ordered array of typed blocks. This gate
checks that every block declares a family this build can render, that the
fields that family needs are present, and that the whole file is
internally consistent.

  - manifest.json parses and lists every chapter index
  - every index references existing section/vocab/exam files
  - block system: known `type`, `variant` recognised, unique ids
  - per-family payloads (exercise points, builder word pools, …)
  - vocab cards carry the full Stimmung-card fields

A new *flavour* inside an existing family is a warning, not an error —
that is the whole point of keeping `variant` free-form: the renderer
styles itself from it and an unknown one degrades to the family default.
A new *family* is an error, because it needs a renderer and a release.

Exit code 0 = valid, 1 = errors found (CI fails the PR).
No third-party dependencies — stdlib only.
"""
import json
import sys
from pathlib import Path

errors = []
warnings = []

SUPPORTED_SCHEMA_VERSION = 2

# family -> variants this build recognises. Unknown variant = warning.
FAMILIES = {
    "NOTE": {"TIP", "USAGE", "CULTURE", "MISTAKE"},
    "LESSON_PAGE": {"DIALOGUE", "GRAMMAR", "VOCAB", "PRONUNCIATION", "READING", "ROLEPLAY"},
    "EXAMPLES": {"PHRASE_LIST", "EXAMPLE_BOX"},
    "GRAMMAR": {"RULE"},
    "PATTERN": {"FORMULA"},
    "BREAKDOWN": {"WORD_BY_WORD"},
    "VOCAB": {"CARD_SET"},
    "EXERCISE": {"MULTIPLE_CHOICE", "FILL_BLANK", "MATCH", "REORDER"},
    "WRITING": {"WORD_POOL"},
    "SUMMARY": {"RECAP"},
}

# Fields every family must carry to render at all.
#
# A tuple means "any one of these satisfies the requirement". Prose is
# expressed that way because `paragraphs` (a list of {lang, text}) replaced
# the single-string `bodyEnglish` / `explanationEnglish` fields: the app's
# proseOf() takes `paragraphs` when present and falls back to the legacy
# strings otherwise, so either is valid but neither is mandatory. Only
# `paragraphs` can carry per-language tags, which is what puts German and
# English on separate cards, so new content should prefer it.
REQUIRED_BY_FAMILY = {
    "NOTE": ["title", ("bodyEnglish", "paragraphs")],
    "LESSON_PAGE": ["headline"],
    "EXAMPLES": ["items"],
    "GRAMMAR": ["ruleHeadline", ("explanationEnglish", "paragraphs")],
    "PATTERN": ["title", "formula"],
    "BREAKDOWN": ["sentenceGerman", "tokens"],
    "EXERCISE": ["prompt"],
    "WRITING": ["promptEnglish", "solutionWords", "wordPool"],
    "SUMMARY": ["bullets", "paragraphs"],
}


def err(path, msg):
    errors.append(f"ERROR   {path}: {msg}")


def warn(path, msg):
    warnings.append(f"WARNING {path}: {msg}")


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        err(path, f"invalid JSON — {e}")
        return None


def require(obj, path, fields, where):
    """Check the required fields of one block. A tuple in `fields` is a
    choice — any one of those names satisfies it; a string is mandatory."""
    for f in fields:
        if isinstance(f, tuple):
            if not any(_present(obj.get(name)) for name in f):
                ors = " or ".join(f"'{n}'" for n in f)
                err(path, f"{where}: missing required field {ors}")
        elif not _present(obj.get(f)):
            err(path, f"{where}: missing required field '{f}'")


def _present(v):
    return v not in ("", None, []) and v != {}


def check_schema_version(path, obj, what, exact=True):
    """`exact` files must match the current version; others (formats that did
    not change, like vocab.json) only need to be no newer than we understand —
    the same rule the app applies before parsing."""
    v = obj.get("schemaVersion")
    if exact:
        if v != SUPPORTED_SCHEMA_VERSION:
            err(path, f"{what} schemaVersion is {v!r}, expected {SUPPORTED_SCHEMA_VERSION}")
    elif isinstance(v, int) and v > SUPPORTED_SCHEMA_VERSION:
        err(path, f"{what} schemaVersion {v} is newer than this validator understands "
                  f"({SUPPORTED_SCHEMA_VERSION})")


# ── Blocks ─────────────────────────────────────────────────────────

def validate_blocks(path, blocks, where, vocab_ids=None):
    """Validate one ordered block array. Returns nothing; records errors."""
    if not isinstance(blocks, list) or not blocks:
        err(path, f"{where}: 'blocks' must be a non-empty array")
        return

    seen = set()
    for i, b in enumerate(blocks):
        where_b = f"{where} block {i}"

        if not isinstance(b, dict):
            err(path, f"{where_b}: must be an object")
            continue

        btype = b.get("type")
        variant = b.get("variant", "")
        bid = b.get("id", "")
        label = f"{btype or '?'}[{variant or '-'}] id={bid or '?'}"

        if not btype:
            err(path, f"{where_b}: missing 'type'")
            continue

        if btype not in FAMILIES:
            err(path, f"{where_b}: unknown block type '{btype}' — "
                      f"a new family needs a renderer and a schemaVersion bump. "
                      f"Known: {', '.join(sorted(FAMILIES))}")
            continue

        if not bid:
            err(path, f"{where_b} ({label}): missing 'id'")
        elif bid in seen:
            err(path, f"{where} block {i} ({label}): duplicate block id — ids must be unique per file")
        else:
            seen.add(bid)

        if variant and variant not in FAMILIES[btype]:
            warn(path, f"{where_b} ({label}): variant '{variant}' is not one of "
                       f"{sorted(FAMILIES[btype])} — it will render with default styling")

        for f in REQUIRED_BY_FAMILY.get(btype, []):
            if isinstance(f, tuple):
                if not any(_present(b.get(name)) for name in f):
                    ors = " or ".join(f"'{n}'" for n in f)
                    err(path, f"{where_b} ({label}): {btype} requires {ors}")
            elif not _present(b.get(f)):
                err(path, f"{where_b} ({label}): {btype} requires '{f}'")

        # Per-family payload rules.
        if btype == "EXERCISE":
            validate_exercise(path, b, where_b, label)
        elif btype == "WRITING":
            check_word_pool(path, b, label)
        elif btype == "BREAKDOWN":
            check_breakdown(path, b, label)
        elif btype == "VOCAB":
            check_vocab_block(path, b, label, vocab_ids)
        elif btype == "GRAMMAR" and b.get("builder"):
            check_word_pool(path, b["builder"], f"{label} builder")

        # House-style warnings — see AI_AUTHORING_SPEC §6 "block house style".
        if btype == "SUMMARY":
            # A recap block, one per lesson. It is not retired: SummaryContent
            # renders it as the closing page of a section.
            if not b.get("bullets") and not b.get("paragraphs"):
                warn(path, f"{where_b} ({label}): SUMMARY has neither 'bullets' nor "
                           f"'paragraphs' — it would render as an empty card")
        elif btype == "GRAMMAR" and not b.get("examples") and not b.get("builder"):
            warn(path, f"{where_b} ({label}): GRAMMAR with neither 'examples' nor 'builder' "
                       f"does not teach the forms — add a paradigm table")
        elif btype == "NOTE":
            body = b.get("bodyEnglish", "") or ""
            if "\n" not in body and len(body) > 160 and not b.get("paragraphs"):
                warn(path, f"{where_b} ({label}): NOTE bodyEnglish is one long line — split "
                           f"it into 2-4 short newline-separated lines (one bullet each)")
        elif btype == "LESSON_PAGE" and str(b.get("variant", "")).upper() == "VOCAB" \
                and not b.get("vocabHighlight"):
            warn(path, f"{where_b} ({label}): LESSON_PAGE VOCAB needs 'vocabHighlight' — a "
                       f"German-only text wall is rejected; list the words as german/english "
                       f"pairs")


def validate_exercise(path, b, where_b, label):
    variant = b.get("variant", "MULTIPLE_CHOICE")
    points = b.get("points")

    if not isinstance(points, int) or points <= 0:
        err(path, f"{where_b} ({label}): every EXERCISE needs 'points' as a positive integer")

    if b.get("concept") is not None:
        require(b["concept"], path, ["title", "rule"], f"{where_b} ({label}) concept")

    if variant == "MULTIPLE_CHOICE":
        opts = b.get("options", [])
        ci = b.get("correctIndex", -1)
        if not opts:
            err(path, f"{where_b} ({label}): MULTIPLE_CHOICE requires 'options'")
        elif not (0 <= ci < len(opts)):
            err(path, f"{where_b} ({label}): correctIndex {ci} out of range (0..{len(opts) - 1})")

    elif variant == "FILL_BLANK":
        items = b.get("items", [])
        if not items:
            err(path, f"{where_b} ({label}): FILL_BLANK requires 'items'")
        for j, item in enumerate(items):
            where_i = f"{where_b} ({label}) item {j}"
            if "___" not in item.get("sentence", ""):
                err(path, f"{where_i}: sentence must contain a '___' gap")
            answers = item.get("answers", [])
            if not answers:
                err(path, f"{where_i}: needs at least one accepted 'answers' entry")

    elif variant == "MATCH":
        pairs = b.get("pairs", [])
        if not pairs:
            err(path, f"{where_b} ({label}): MATCH requires 'pairs'")
        else:
            left = [p.get("german") for p in pairs]
            if len(set(left)) != len(left):
                err(path, f"{where_b} ({label}): MATCH german sides must be distinct")
            if len(left) < 2:
                warn(path, f"{where_b} ({label}): MATCH needs at least two pairs to be worth playing")

    elif variant == "REORDER":
        builder = b.get("builder")
        if not builder:
            err(path, f"{where_b} ({label}): REORDER requires a 'builder'")
        else:
            check_word_pool(path, builder, f"{label} builder")

    else:
        warn(path, f"{where_b} ({label}): exercise variant '{variant}' is not scored by the app")


def check_word_pool(path, obj, label):
    solution = obj.get("solutionWords", [])
    pool = obj.get("wordPool", [])
    if not solution:
        err(path, f"{label}: needs 'solutionWords'")
    if not pool:
        err(path, f"{label}: needs 'wordPool'")
    if solution and pool and not set(solution) <= set(pool):
        missing = sorted(set(solution) - set(pool))
        err(path, f"{label}: solutionWords must all appear in wordPool — missing {missing}")


def check_breakdown(path, b, label):
    sentence = b.get("sentenceGerman", "")
    tokens = b.get("tokens", [])
    if not sentence:
        return
    # Every gloss token should actually occur in the sentence being glossed,
    # otherwise the breakdown silently drifts away from what it explains.
    flattened = sentence.replace(",", " ").replace(".", " ").replace("!", " ")
    for t in tokens:
        word = t.get("token", "")
        if word and word not in flattened:
            err(path, f"{label}: gloss token '{word}' does not appear in '{sentence}'")


def check_vocab_block(path, b, label, vocab_ids):
    ids = b.get("wordIds", [])
    inline = b.get("words", [])
    if not ids and not inline:
        err(path, f"{label}: VOCAB needs 'wordIds' or inline 'words'")
    if ids and vocab_ids is not None:
        unknown = [i for i in ids if i not in vocab_ids]
        if unknown:
            err(path, f"{label}: wordIds not found in vocab.json: {unknown}")


# ── Files ──────────────────────────────────────────────────────────

def load_vocab_ids(path: Path):
    bank = load(path)
    if bank is None:
        return None
    return {w.get("id") for w in bank.get("words", [])}


def validate_index(chapter_dir: Path, index_path: Path):
    idx = load(index_path)
    if idx is None:
        return None
    require(idx, index_path, ["chapterId", "number", "titleGerman", "titleEnglish", "sections"], "index")
    check_schema_version(index_path, idx, "index")

    seen_ids = set()
    for s in idx.get("sections", []):
        sid = s.get("id", "?")
        if sid in seen_ids:
            err(index_path, f"duplicate section id '{sid}'")
        seen_ids.add(sid)
        require(s, index_path, ["id", "title", "file"], f"section '{sid}'")
        if not isinstance(s.get("version"), int):
            err(index_path, f"section '{sid}': missing integer 'version' — the OTA sync needs it to detect updates")

    vocab_ids = None
    for f in (idx.get("vocabFile", "vocab.json"), idx.get("examFile", "exam.json")):
        fp = chapter_dir / f
        if not fp.exists():
            err(index_path, f"missing referenced file '{f}'")
        elif f.endswith("vocab.json"):
            vocab_ids = load_vocab_ids(fp)
            validate_vocab(fp, seen_ids)
        elif f.endswith("exam.json"):
            validate_exam(fp)

    # Sections come after vocab so VOCAB blocks can resolve their wordIds.
    for s in idx.get("sections", []):
        section_file = chapter_dir / s.get("file", "")
        if section_file.exists():
            validate_section(section_file, s.get("id", "?"), vocab_ids)
    return idx


def validate_section(path: Path, section_id: str, vocab_ids=None):
    sec = load(path)
    if sec is None:
        return
    check_schema_version(path, sec, "section")
    require(sec, path, ["id", "title", "blocks"], f"section '{section_id}'")
    if sec.get("id") != section_id:
        err(path, f"section id '{sec.get('id')}' does not match index reference '{section_id}'")

    legacy = [k for k in ("corePages", "grammar", "patterns", "writing", "practice") if k in sec]
    if legacy:
        err(path, f"section '{section_id}': the v1 slots {legacy} were replaced by 'blocks' in schema v2")

    validate_blocks(path, sec.get("blocks", []), f"section '{section_id}'", vocab_ids)


def validate_vocab(path: Path, section_ids: set):
    bank = load(path)
    if bank is None:
        return
    # vocab.json did not change between v1 and v2 — it only must not be
    # newer than this build can read.
    check_schema_version(path, bank, "vocab bank", exact=False)
    seen = set()
    for card in bank.get("words", []):
        wid = card.get("id", "?")
        where = f"vocab '{wid}'"
        if wid in seen:
            err(path, f"duplicate word id '{wid}'")
        seen.add(wid)
        require(card, path, ["id", "word", "partOfSpeech", "meaningsEnglish", "ipa"], where)
        pos = card.get("partOfSpeech")
        if pos == "NOUN":
            if not card.get("article") or not card.get("gender"):
                err(path, f"{where}: nouns need 'article' and 'gender'")
        if pos == "VERB" and card.get("regular") is None:
            warn(path, f"{where}: verb without 'regular' flag")
        for sid in card.get("sectionIds", []):
            if section_ids and sid not in section_ids:
                err(path, f"{where}: unknown sectionIds '{sid}'")


def validate_exam(path: Path):
    paper = load(path)
    if paper is None:
        return
    check_schema_version(path, paper, "exam")
    require(paper, path, ["chapterId", "blocks"], "exam")
    validate_blocks(path, paper.get("blocks", []), "exam")

    concepts = [b for b in paper.get("blocks", [])
                if isinstance(b, dict) and b.get("concept") is not None]
    if not concepts:
        warn(path, "exam: no exercise carries a 'concept' — nothing can be saved to the concept book")


def main():
    root = Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else Path(".")
    manifest_path = root / "manifest.json"
    manifest = load(manifest_path)
    if manifest is None:
        report()
        return 1
    require(manifest, manifest_path, ["contentVersion", "remoteBaseUrl", "chapters"], "manifest")
    check_schema_version(manifest_path, manifest, "manifest")

    for ref in manifest.get("chapters", []):
        index_rel = ref.get("indexFile", "")
        index_path = root / index_rel
        if not index_path.exists():
            err(manifest_path, f"chapter '{ref.get('id')}' references missing index '{index_rel}'")
            continue
        idx = validate_index(index_path.parent, index_path)
        if idx and idx.get("chapterId") != ref.get("id"):
            err(index_path, f"chapterId '{idx.get('chapterId')}' != manifest id '{ref.get('id')}'")

    report()
    return 1 if errors else 0


def report():
    for line in warnings:
        print(line)
    for line in errors:
        print(line)
    total = len(errors)
    print(f"\n{'FAIL' if total else 'PASS'}: {total} error(s), {len(warnings)} warning(s)")
    print("hint: a section is an ordered 'blocks' array; 'type' picks the renderer, "
          "'variant' only styles it. Word ids like 'w_stadt' are unique per chapter.")


if __name__ == "__main__":
    sys.exit(main())
