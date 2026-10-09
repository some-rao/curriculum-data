#!/usr/bin/env python3
"""
GermanFlow curriculum validator.

Run:  python3 validate.py [--root .]

Validates the split curriculum schema before merge:
  - manifest.json parses and lists every chapter index
  - every index references existing section/vocab/exam files
  - section referential integrity (IDs unique, practice answers in range)
  - vocab cards carry the full Stimmung-card fields
  - exam answers in range; concept blocks well-formed

Exit code 0 = valid, 1 = errors found (CI fails the PR).
No third-party dependencies — stdlib only.
"""
import json
import re
import sys
from pathlib import Path

errors = []
warnings = []


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
    for f in fields:
        if f not in obj or obj[f] in ("", None, []):
            err(path, f"{where}: missing required field '{f}'")


def validate_index(chapter_dir: Path, index_path: Path):
    idx = load(index_path)
    if idx is None:
        return None
    require(idx, index_path, ["chapterId", "number", "titleGerman", "titleEnglish", "sections"], "index")
    if idx.get("schemaVersion", 1) > 1:
        warn(index_path, f"schemaVersion {idx['schemaVersion']} > 1 (validator may lag)")

    seen_ids = set()
    for s in idx.get("sections", []):
        sid = s.get("id", "?")
        if sid in seen_ids:
            err(index_path, f"duplicate section id '{sid}'")
        seen_ids.add(sid)
        require(s, index_path, ["id", "title", "file"], f"section '{sid}'")
        section_file = chapter_dir / s.get("file", "")
        if not section_file.exists():
            err(index_path, f"section '{sid}' references missing file '{s.get('file')}'")
        else:
            validate_section(section_file, sid)

    for f in (idx.get("vocabFile", "vocab.json"), idx.get("examFile", "exam.json")):
        fp = chapter_dir / f
        if not fp.exists():
            err(index_path, f"missing referenced file '{f}'")
        elif f.endswith("vocab.json"):
            validate_vocab(fp, seen_ids)
        elif f.endswith("exam.json"):
            validate_exam(fp)
    return idx


def validate_section(path: Path, section_id: str):
    sec = load(path)
    if sec is None:
        return
    require(sec, path, ["id", "corePages"], f"section '{section_id}'")
    if sec.get("id") != section_id:
        err(path, f"section id '{sec.get('id')}' does not match index reference '{section_id}'")

    for q in sec.get("practice", []):
        opts = q.get("options", [])
        ci = q.get("correctIndex", -1)
        if not (0 <= ci < len(opts)):
            err(path, f"practice '{q.get('id')}': correctIndex {ci} out of range (0..{len(opts)-1})")

    for name in ("grammar", "writing"):
        mod = sec.get(name)
        if mod and "solutionWords" not in str(mod):
            pass  # builder lives inside grammar; writing has its own shape

    w = sec.get("writing")
    if w:
        require(w, path, ["promptEnglish", "solutionWords", "wordPool"], "writing module")
        if not set(w.get("solutionWords", [])) <= set(w.get("wordPool", [])):
            err(path, "writing: solutionWords must all appear in wordPool")

    g = sec.get("grammar")
    if g and g.get("builder"):
        b = g["builder"]
        if not set(b.get("solutionWords", [])) <= set(b.get("wordPool", [])):
            err(path, "grammar.builder: solutionWords must all appear in wordPool")


def validate_vocab(path: Path, section_ids: set):
    bank = load(path)
    if bank is None:
        return
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
    require(paper, path, ["chapterId", "questions"], "exam")
    for q in paper.get("questions", []):
        opts = q.get("options", [])
        ci = q.get("correctIndex", -1)
        where = f"exam '{q.get('id')}'"
        if not (0 <= ci < len(opts)):
            err(path, f"{where}: correctIndex {ci} out of range")
        c = q.get("concept")
        if c is not None:
            require(c, path, ["title", "rule"], f"{where} concept")


def main():
    root = Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else Path(".")
    manifest_path = root / "manifest.json"
    manifest = load(manifest_path)
    if manifest is None:
        report()
        return 1
    require(manifest, manifest_path, ["contentVersion", "remoteBaseUrl", "chapters"], "manifest")

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
    print("hint: word ids like 'w_stadt' must be globally unique per chapter; "
          "section files must match their index reference exactly.")


if __name__ == "__main__":
    sys.exit(main())
