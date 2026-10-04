#!/usr/bin/env python3
"""Read-only lookup of the portable CW corpus; translation remains contextual."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
import threading
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("entity", "term", "example", "text", "pattern")
REVIEW_STATUSES = frozenset(("needs_alignment_review", "alignment_conflict", "known_translation_conflict"))

# Parsed and normalized corpus, loaded once per file version. Queries then
# score in memory instead of re-reading and re-normalizing every record.
_CACHE: dict[tuple, dict] = {}
_CACHE_LOCK = threading.Lock()


def corpus_path() -> Path:
    """CW_CORPUS_PATH selects another corpus, e.g. the exported chat dictionary."""
    override = os.environ.get("CW_CORPUS_PATH")
    return Path(override) if override else ROOT / "references" / "corpus.sqlite3"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("’", "'")
    value = re.sub(r"\s*([>])\s*", r"\1", value)
    return re.sub(r"\s+", " ", value).strip(" \t\r\n.!?。！？\"“”")


def parts(value: str) -> list[str]:
    # Keep the original phrase; alternate translations remain candidates.
    return list(dict.fromkeys([value, *re.split(r"[/／、|]", value)]))


def contains(haystack: str, needle: str) -> bool:
    # A missing substring cannot satisfy word boundaries. Avoid compiling a
    # different regular expression for every unrelated corpus phrase.
    if not needle or needle not in haystack:
        return False
    if re.fullmatch(r"[a-z0-9' >/_-]+", needle):
        return re.search(r"(?<![a-z0-9_])" + re.escape(needle) + r"(?![a-z0-9_])", haystack) is not None
    return needle in haystack


def score(query: str, values: list[str], fuzzy: bool = False) -> float:
    return score_normalized(query, [v for v in map(normalize, values) if v], fuzzy)


def score_normalized(query: str, values: list[str], fuzzy: bool = False) -> float:
    """score() for values that are already normalized and nonempty."""
    best = 0.0
    for v in values:
        if query == v:
            return 100.0
        # Resolve observed singular/plural names against real corpus entries.
        # This is a retrieval equivalence, never a generated entity or alias.
        if min(len(query), len(v)) >= 5 and (query == v + "s" or v == query + "s"):
            best = max(best, 96.0)
        if len(query) >= 2 and contains(v, query):
            best = max(best, 80 - min(25, (len(v) - len(query)) * 0.15))
        if len(v) >= 2 and contains(query, v):
            best = max(best, 65 + min(14, len(v) * 0.3))
        # Do not turn short abbreviations such as HP into HB by edit distance.
        if fuzzy and len(query) >= 4 and len(v) >= 4:
            ratio = difflib.SequenceMatcher(None, query, v).ratio()
            if ratio >= 0.78:
                best = max(best, ratio * 55)
    return best


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def load_curated(conn: sqlite3.Connection) -> list[dict]:
    """User-confirmed terms first, then website aliases not already covered.

    An exported chat dictionary carries them in its `curated` table; the full
    Skill corpus reads the two JSON files beside it.
    """
    if has_table(conn, "curated"):
        return [json.loads(row[0]) for row in conn.execute("SELECT entry_json FROM curated ORDER BY position")]
    entries = json.loads((ROOT / "references" / "curated-terms.json").read_text(encoding="utf-8"))["entries"]
    website = ROOT / "references" / "website-reference.json"
    primary = {normalize(entry["en"]) for entry in entries}
    for entry in json.loads(website.read_text(encoding="utf-8"))["entries"]:
        if normalize(entry["en"]) not in primary:
            entries.append(entry)
    return entries


def read_curated(query: str) -> list[dict]:
    return [dict(entry) for entry, values in corpus_index()["curated"] if score_normalized(query, values) > 0]


def connect() -> sqlite3.Connection:
    path = corpus_path()
    if not path.is_file():
        raise FileNotFoundError(f"Corpus {path.name} is missing; restore the complete Skill folder or dictionary file.")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def corpus_index() -> dict:
    """Load records once per corpus file version (path, size, modification time)."""
    path = corpus_path()
    try:
        stat = path.stat()
    except OSError:
        connect()  # Raises the missing-corpus error.
        raise
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns,
           *(p.stat().st_mtime_ns for p in (ROOT / "references" / "curated-terms.json",
                                             ROOT / "references" / "website-reference.json") if p.is_file()))
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
        conn = connect()
        try:
            records = []
            project_names: dict[str, list[dict]] = {}
            for row in conn.execute("SELECT id,kind,en,zh,aliases_json,entity_key,mode,status,source_id FROM records ORDER BY id"):
                values = [*parts(row["en"]), *parts(row["zh"]), *json.loads(row["aliases_json"])]
                entity_key = row["entity_key"]
                if entity_key:
                    values += [entity_key, entity_key.split(":", 1)[-1]]
                en_values = [v for v in [normalize(row["en"])] if v]
                records.append((row["id"], row["kind"], row["mode"], row["status"],
                                [v for v in map(normalize, values) if v], en_values))
                if row["kind"] == "entity" and row["source_id"] == "project_catalog" and row["zh"]:
                    project_names.setdefault(normalize(row["en"]), []).append(
                        {"en": row["en"], "zh": row["zh"], "entity_key": entity_key})
            curated = [(entry, [v for v in map(normalize, [entry["en"], entry["zh"], *entry.get("aliases", [])]) if v])
                       for entry in load_curated(conn)]
            direct = {}
            if has_table(conn, "direct"):
                direct = {row["zh_norm"]: {"en": row["en"], "mode": row["mode"]}
                          for row in conn.execute("SELECT zh_norm,en,mode FROM direct")}
            meta = dict(conn.execute("SELECT key,value FROM meta").fetchall()) if has_table(conn, "meta") else {}
        finally:
            conn.close()
        # Different file versions never share a cache slot; drop the stale one.
        _CACHE.clear()
        _CACHE[key] = index = {"records": records, "project_names": project_names,
                               "curated": curated, "direct": direct, "meta": meta}
        return index


def direct_match(text: str) -> dict | None:
    """Whole-message answer from an exported dictionary's confirmed chat samples."""
    normalized = normalize(text)
    return corpus_index()["direct"].get(normalized) if normalized else None


def unpack(row: sqlite3.Row, full: bool = False) -> dict:
    result = dict(row)
    result["aliases"] = json.loads(result.pop("aliases_json", "[]"))
    if "metadata_json" in result:
        metadata = json.loads(result.pop("metadata_json") or "{}")
        if full:
            result["metadata"] = metadata
        else:
            # Return useful source context without dumping every game fact.
            keys = ("original_text", "raw", "notes", "scope", "active", "visible", "translation_status", "raw_regex")
            result["context"] = {k: v for k, v in metadata.items() if k in keys}
    return result


def lookup(query: str, *, kind: str | None = None, mode: str | None = None,
           limit: int = 5, fuzzy: bool = False, include_review: bool = False) -> dict:
    normalized = normalize(query)
    if not normalized:
        raise ValueError("Enter a nonempty name, phrase or entity ID.")
    index = corpus_index()
    curated = read_curated(normalized)
    expansions = [normalize(r["entity_english"]) for r in curated if r.get("entity_english")]
    selected_kinds = [kind] if kind else list(KINDS)
    grouped: dict[str, list[tuple[float, int]]] = {k: [] for k in selected_kinds}
    project_names = index["project_names"]
    conn = connect()
    try:
        for record_id, record_kind, record_mode, status, values, en_values in index["records"]:
            if (not include_review and status in REVIEW_STATUSES) or (kind and record_kind != kind) \
                    or (mode and record_mode != mode):
                continue
            rank = score_normalized(normalized, values, fuzzy)
            if record_kind == "entity":
                for expansion in expansions:
                    rank = max(rank, score_normalized(expansion, en_values) * 0.99)
            if rank > 0:
                # Equal name matches prefer the project export over supplements.
                if record_kind == "entity" and "supplement" in status:
                    rank -= 0.5
                grouped[record_kind].append((rank, record_id))
        result = {"query": query, "curated_matches": curated, "groups": {}}
        for record_kind, candidates in grouped.items():
            candidates.sort(key=lambda item: (-item[0], item[1]))
            selected, seen = [], set()
            for rank, record_id in candidates:
                row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
                # Keep real differences, collapse the same pair in multiple modes.
                key = (row["en"], row["zh"], row["entity_key"])
                if key in seen:
                    continue
                seen.add(key)
                record = unpack(row)
                record["match_score"] = round(rank, 2)
                if record_kind == "example" and normalize(row["en"]) in project_names:
                    canonical = project_names[normalize(row["en"])]
                    if row["zh"] not in {r["zh"] for r in canonical}:
                        record["project_name_candidates"] = canonical
                        record["name_pair_note"] = "原名称样例与项目正式译名不同。正式名称使用项目候选；不同原译名须结合语境核对，不能自动认定都是有效别名。"
                selected.append(record)
                if len(selected) >= limit:
                    break
            if selected:
                result["groups"][record_kind] = selected
        result["note"] = "候选供语境判断。玩家表达以附件为主；正式实体名称以项目目录为主。匹配分数不是翻译正确率。默认隔离尚未核对的任务字段中英配对。"
        return result
    finally:
        conn.close()


def brief_result(result: dict) -> dict:
    """Keep translation evidence small; --id and --details retain provenance."""
    output = {"query": result["query"]}
    if result["curated_matches"]:
        output["guidance"] = [
            {k: entry[k] for k in ("en", "zh", "aliases", "notes") if k in entry}
            for entry in result["curated_matches"]
        ]
    if result["groups"]:
        fields = ("id", "en", "zh", "status", "entity_key", "project_name_candidates", "name_pair_note")
        output["groups"] = {
            kind: [{k: row[k] for k in fields if row.get(k)} for row in rows]
            for kind, rows in result["groups"].items()
        }
    if not result["curated_matches"] and not result["groups"]:
        output["no_match"] = True
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="*", help="One or more terms; batch unfamiliar names in one invocation")
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--mode", help="Exact sample mode, e.g. cn_to_en_short")
    parser.add_argument("--limit", type=int, default=5, help="Maximum results per group (1-30)")
    parser.add_argument("--id", type=int, help="Read one full record, including source details")
    parser.add_argument("--fuzzy", action="store_true", help="Allow spelling candidates for terms of 4+ characters")
    parser.add_argument("--include-review", action="store_true", help="Include quarantined source pairs for source auditing, not default translation")
    parser.add_argument("--details", action="store_true", help="Return full candidate fields and source locations instead of brief output")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit must be between 1 and 30")
    try:
        if args.id is not None:
            conn = connect()
            try:
                row = conn.execute("SELECT * FROM records WHERE id = ?", (args.id,)).fetchone()
                if row is None:
                    parser.error("Record ID does not exist")
                output = unpack(row, full=True)
            finally:
                conn.close()
        elif args.query:
            results = []
            for query in args.query:
                result = lookup(query, kind=args.kind, mode=args.mode, limit=args.limit, fuzzy=args.fuzzy, include_review=args.include_review)
                results.append(result if args.details else brief_result(result))
            output = results[0] if len(results) == 1 else results
        else:
            parser.error("Provide a query or --id")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.details or args.id is not None else None))


if __name__ == "__main__":
    main()
