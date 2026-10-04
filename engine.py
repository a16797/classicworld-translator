"""Translation pipeline: my phrasebook -> cache -> built-in phrases & dictionary samples -> DeepSeek.

The reviewed translation core ships in vendor/; this module adds per-user
layers and friendly errors.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from settings import USER_DIR

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DICT_FILE = DATA_DIR / "cw-chat-dict.sqlite3"
DEFAULT_PHRASEBOOK = DATA_DIR / "默认喊话表.csv"
USER_PHRASEBOOK = USER_DIR / "我的喊话表.csv"
CACHE_FILE = USER_DIR / "cache.json"
CACHE_LIMIT = 3000
PHRASEBOOK_HEADER = ("中文", "英文简写")

if not FROZEN:
    sys.path.insert(0, str(APP_DIR / "vendor"))
os.environ["CW_CORPUS_PATH"] = str(DICT_FILE)

import fast_translate as ft  # noqa: E402
import lookup  # noqa: E402

ROUTE_NAMES = {"phrasebook": "喊话表", "cache": "翻译记录", "local": "内置短句",
               "direct": "词库原句", "generation": "DeepSeek"}


@dataclass
class Result:
    text: str = ""
    route: str = ""
    ms: float = 0.0
    error: str = ""


def friendly_error(error: Exception) -> str:
    message = str(error)
    if "not configured" in message:
        return "词库里没有这句，要联网翻译：请点“设置”填写 DeepSeek Key"
    if message == "HTTP 401":
        return "DeepSeek Key 不对，请到设置里重新粘贴"
    if message == "HTTP 402":
        return "DeepSeek 账户余额不足，请到 DeepSeek 开放平台充值"
    if message == "HTTP 429":
        return "请求太频繁，稍等几秒再试"
    if message.startswith("HTTP 5"):
        return "DeepSeek 服务暂时出错，稍后再试"
    if message == "timeout":
        return "联网超时，检查网络后再试"
    if message == "network error":
        return "连不上 DeepSeek，检查网络或代理"
    if message.startswith("HTTP"):
        return f"DeepSeek 返回错误（{message}）"
    return f"翻译失败：{message}"


def read_csv(path: Path) -> list[tuple[str, str]]:
    # Excel may save as UTF-8 (with BOM) or the system code page (GBK).
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open(encoding=encoding, newline="") as file:
                rows = list(csv.reader(file))
            break
        except UnicodeDecodeError:
            continue
        except OSError:
            return []
    else:
        return []
    pairs = []
    for row in rows:
        if len(row) >= 2 and row[0].strip() and row[1].strip() and tuple(c.strip() for c in row[:2]) != PHRASEBOOK_HEADER:
            pairs.append((row[0].strip(), row[1].strip()))
    return pairs


class Phrasebook:
    """Default phrases shipped with the app, overridden by the user's own file (reloaded when edited)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, str, str]] = {}  # normalized -> (中文, 英文, source)
        self._stamp: tuple = ()
        self._lock = threading.Lock()

    def _stamp_now(self) -> tuple:
        return tuple(p.stat().st_mtime_ns if p.is_file() else 0 for p in (DEFAULT_PHRASEBOOK, USER_PHRASEBOOK))

    def _refresh(self) -> None:
        stamp = self._stamp_now()
        if stamp == self._stamp:
            return
        entries = {}
        for path, source in ((DEFAULT_PHRASEBOOK, "phrasebook"), (USER_PHRASEBOOK, "mine")):
            for zh, en in read_csv(path):
                key = lookup.normalize(zh)
                if key:
                    entries[key] = (zh, en, source)
        self._entries, self._stamp = entries, stamp

    def get(self, text: str) -> str | None:
        with self._lock:
            self._refresh()
            found = self._entries.get(lookup.normalize(text))
            return found[1] if found else None

    def entries(self) -> list[tuple[str, str, str]]:
        with self._lock:
            self._refresh()
            return list(self._entries.values())

    def remember(self, zh: str, en: str) -> None:
        """Add or replace one line in the user's phrasebook."""
        with self._lock:
            key = lookup.normalize(zh)
            rows = [(z, e) for z, e in read_csv(USER_PHRASEBOOK) if lookup.normalize(z) != key]
            rows.append((zh.strip(), en.strip()))
            USER_DIR.mkdir(parents=True, exist_ok=True)
            tmp = USER_PHRASEBOOK.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(PHRASEBOOK_HEADER)
                writer.writerows(rows)
            tmp.replace(USER_PHRASEBOOK)
            self._stamp = ()

    @staticmethod
    def ensure_user_file() -> Path:
        if not USER_PHRASEBOOK.is_file():
            USER_DIR.mkdir(parents=True, exist_ok=True)
            with USER_PHRASEBOOK.open("w", encoding="utf-8-sig", newline="") as file:
                csv.writer(file).writerow(PHRASEBOOK_HEADER)
        return USER_PHRASEBOOK


class Cache:
    """Earlier DeepSeek answers, so a repeated message is instant and free.

    Tied to the dictionary version and model: a new dictionary or model starts fresh.
    """

    def __init__(self, version: str) -> None:
        self.version = version
        self.items: dict[str, str] = {}
        self._lock = threading.Lock()
        try:
            stored = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if stored.get("version") == version:
                self.items = dict(stored.get("items", {}))
        except (OSError, ValueError, AttributeError):
            pass

    def get(self, text: str) -> str | None:
        return self.items.get(lookup.normalize(text))

    def put(self, text: str, value: str) -> None:
        with self._lock:
            key = lookup.normalize(text)
            self.items.pop(key, None)
            self.items[key] = value  # newest last
            while len(self.items) > CACHE_LIMIT:
                self.items.pop(next(iter(self.items)))
            snapshot = {"version": self.version, "items": dict(self.items)}
        try:
            USER_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CACHE_FILE)
        except OSError:
            pass

    def forget(self, text: str) -> None:
        with self._lock:
            self.items.pop(lookup.normalize(text), None)


@dataclass
class Suggestion:
    zh: str
    en: str
    source: str  # key of SOURCE_NAMES
    rank: float = 0.0  # match quality, lower is closer


SOURCE_NAMES = {"compose": "拼好的", "mine": "我的", "phrasebook": "常用", "sample": "说法", "term": "说法",
                "item": "物品", "monster": "怪物", "map": "地图", "npc": "NPC", "skill": "技能"}
SOURCE_PRIORITY = {"compose": -1, "mine": 0, "phrasebook": 1}
ENTITY_TYPES = ("item", "monster", "map", "npc", "skill")  # quests and recipes are not chat material

# Dropdown layout: a short "recommended" block, then one group per category in this fixed order.
# "推荐" leads (translating is the main job): trade lines built for you, lines you use often, exact matches,
# then all player wording — whole chat lines and slang terms together, your phrasebook first.
# The game-name lookups follow as a bonus, one group per category.
WORDING = ("mine", "phrasebook", "sample", "term")
GROUPS = [("物品", ("item",)), ("怪物", ("monster",)), ("技能", ("skill",)), ("地图", ("map",)), ("NPC", ("npc",))]
TOP_LIMIT, RECOMMENDED_LIMIT, GROUP_LIMIT = 4, 12, 6
GROUP_LIMITS: dict[str, int] = {}
USAGE_FILE = USER_DIR / "usage.json"


class Usage:
    """How often each dropdown line was picked or copied; frequently used lines are recommended first."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self._lock = threading.Lock()
        try:
            self.counts = {k: int(v) for k, v in json.loads(USAGE_FILE.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            pass

    @staticmethod
    def key(zh: str, en: str) -> str:
        return f"{lookup.normalize(zh)}\t{en.strip()}"

    def count(self, zh: str, en: str) -> int:
        return self.counts.get(self.key(zh, en), 0)

    def bump(self, zh: str, en: str) -> None:
        with self._lock:
            key = self.key(zh, en)
            self.counts[key] = self.counts.get(key, 0) + 1
            snapshot = dict(self.counts)
        try:
            USER_DIR.mkdir(parents=True, exist_ok=True)
            tmp = USAGE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp.replace(USAGE_FILE)
        except OSError:
            pass

# 收柠檬 -> B> Lemon. Longest prefix first.
TRADE_PREFIXES = [("求购", "B>"), ("收购", "B>"), ("出售", "S>"), ("收", "B>"), ("买", "B>"),
                  ("卖", "S>"), ("出", "S>"), ("换", "T>"), ("求", "LF")]


class SuggestionIndex:
    """Fuzzy search over ready-made lines: phrasebooks, samples, slang terms and every game name."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []  # (search key, zh shown, en, source)
        self.names: dict[str, tuple[str, str, str]] = {}  # normalized Chinese name -> (zh, en, type)

    def load(self) -> None:
        conn = sqlite3.connect(DICT_FILE.as_uri() + "?mode=ro", uri=True)
        try:
            rows = [(zh, zh, en, "sample") for zh, en in conn.execute("SELECT zh, en FROM direct")]
            rows += [(zh, zh, en, "term") for zh, en in conn.execute(
                "SELECT zh, en FROM records WHERE kind IN ('term','pattern') AND zh != '' AND en != ''")]
            # Project names before website supplements, so the official pair wins a shared name.
            entities = conn.execute(
                "SELECT zh, en, aliases_json, entity_key FROM records WHERE kind='entity' AND zh != '' AND en != '' "
                "ORDER BY source_id != 'project_catalog', id").fetchall()
        finally:
            conn.close()
        names: dict[str, tuple[str, str, str]] = {}
        for zh, en, aliases, key in entities:
            kind = key.split(":", 1)[0]
            if kind not in ENTITY_TYPES or re.fullmatch(r"Item \d+", en):
                continue  # placeholder English is not a real name
            chinese = {zh, *(a for a in json.loads(aliases) if re.search(r"[㐀-鿿]", a))}
            for alias in chinese:
                rows.append((alias, zh, en, kind))
                names.setdefault(lookup.normalize(alias), (zh, en, kind))
        self.rows = [(lookup.normalize(key), zh, en, source) for key, zh, en, source in rows
                     if "{" not in key and lookup.normalize(key)]
        self.names = names

    def compose(self, q: str) -> list[tuple]:
        """收柠檬 / 卖齿轮镖100个 / 换扎昆头盔 -> a ready trade line built from the official name."""
        for prefix, tag in TRADE_PREFIXES:
            if not q.startswith(prefix):
                continue
            rest = q[len(prefix):].strip()
            # Longest item name at the start, optionally followed by a quantity (100个 / 100 / x100).
            for end in range(len(rest), 0, -1):
                found = self.names.get(rest[:end].strip())
                if found and found[2] == "item":
                    tail = rest[end:].strip()
                    count = re.fullmatch(r"[x×]?\s*(\d+)\s*(?:个|组|张|件)?", tail)
                    if tail and not count:
                        break
                    english = f"{tag} {found[1]}" + (f" x{count.group(1)}" if count else "")
                    return [(-1, -1, 0, f"{prefix}{found[0]}{tail}", english, "compose")]
            break
        return []

    def search(self, query: str, phrasebook: list[tuple[str, str, str]], usage: Usage | None = None
               ) -> list[tuple[str, list[Suggestion]]]:
        """Grouped results: [("推荐", [...]), ("句子", [...]), ("物品", [...]), ...]; empty groups omitted."""
        matches = self.match(query, phrasebook)
        if not matches:
            return []
        used = (lambda s: usage.count(s.zh, s.en)) if usage else (lambda s: 0)
        # Recommended: ready-made trade line, then lines you used before (most used first), then exact matches.
        top = [s for s in matches if s.source == "compose"]
        top += sorted((s for s in matches if s.source != "compose" and s.rank <= 2.5 and used(s)),
                      key=lambda s: (-used(s), s.rank, len(s.zh)))
        top += [s for s in matches if s.rank == 0 and s.source != "compose"]
        recommended, seen = [], set()
        for s in top:
            if (s.zh, s.en) not in seen and len(recommended) < TOP_LIMIT:
                seen.add((s.zh, s.en))
                recommended.append(s)
        # Then all player wording (whole lines and slang terms, your phrasebook first), closest first.
        for s in matches:
            if len(recommended) >= RECOMMENDED_LIMIT:
                break
            if s.source in WORDING and (s.zh, s.en) not in seen:
                seen.add((s.zh, s.en))
                recommended.append(s)
        groups = [("推荐", recommended)] if recommended else []
        for title, sources in GROUPS:
            items = [s for s in matches if s.source in sources and (s.zh, s.en) not in seen]
            items = items[:GROUP_LIMITS.get(title, GROUP_LIMIT)]
            if items:
                groups.append((title, items))
        return groups

    def match(self, query: str, phrasebook: list[tuple[str, str, str]]) -> list[Suggestion]:
        """Every matching line, closest first."""
        q = lookup.normalize(query)
        if not q:
            return []
        rows = [(lookup.normalize(zh), zh, en, source) for zh, en, source in phrasebook] + self.rows
        chinese = bool(re.search(r"[㐀-鿿]", q))
        chars = {c for c in q if re.match(r"[㐀-鿿]", c)}
        scored = self.compose(q)
        for key, zh, en, source in rows:
            if key == q:
                rank = 0.0
            elif key.startswith(q):
                rank = 1.0
            elif q in key:
                rank = 2.0
            elif len(key) >= 2 and key in q and source in ENTITY_TYPES:
                rank = 2.5  # a game name inside a longer sentence, e.g. 收柠檬100个
            elif not chinese and re.search(r"(?<![a-z])" + re.escape(q), en.casefold()):
                rank = 3.0  # English typed: match the start of an English word
            elif chinese and len(chars) >= 2 and chars <= set(key):
                rank = 4.0  # every Chinese character appears, in any order: loose match
            else:
                continue
            # Own lines first, then shorter (more reusable) lines.
            scored.append((rank, SOURCE_PRIORITY.get(source, 2), len(zh), zh, en, source))
        scored.sort()
        results, seen = [], set()
        for rank, _, _, zh, en, source in scored:
            key = (lookup.normalize(zh), en.casefold())  # the same name reached through several aliases
            if key not in seen:
                seen.add(key)
                results.append(Suggestion(zh, en, source, rank))
        return results


class Engine:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.client = ft.GenerationClient()
        self.phrasebook = Phrasebook()
        self.suggestions = SuggestionIndex()
        self.usage = Usage()
        self.cache: Cache | None = None
        self.ready = threading.Event()
        self._last_network = 0.0

    def dictionary_info(self) -> dict:
        return lookup.corpus_index()["meta"] if self.ready.is_set() else {}

    def cache_version(self) -> str:
        # A new dictionary, model or prompt makes earlier answers stale.
        prompt = hashlib.sha1(ft.CHAT_SYSTEM.encode("utf-8")).hexdigest()[:10]
        return f"{self.dictionary_info().get('exported_at', '')}|{self.settings['model']}|{prompt}"

    def preload(self) -> None:
        """Load the dictionary into memory once (runs in the background at startup)."""
        try:
            lookup.corpus_index()
            self.ready.set()
            self.cache = Cache(self.cache_version())
            self.suggestions.load()
            self.phrasebook.get("")
        finally:
            self.ready.set()

    def reset_cache_for_model(self) -> None:
        if self.ready.is_set():
            self.cache = Cache(self.cache_version())

    def suggest(self, text: str) -> list[tuple[str, list[Suggestion]]]:
        if not self.ready.is_set():
            return []
        return self.suggestions.search(text, self.phrasebook.entries(), self.usage)

    def used(self, zh: str, en: str) -> None:
        """A dropdown line or translation was picked/copied: recommend it sooner next time."""
        if zh.strip() and en.strip():
            self.usage.bump(zh, en)

    def warm(self) -> None:
        """Open (or refresh) the DeepSeek connection while the user is still typing."""
        if not self.settings.api_key:
            return

        def run() -> None:
            # Servers drop idle keep-alive connections; reconnect if it sat idle.
            if time.monotonic() - self._last_network > 20:
                self.client.close()
            self.client.warm()
            self._last_network = time.monotonic()

        threading.Thread(target=run, daemon=True, name="warm").start()

    def translate(self, text: str) -> Result:
        start = time.perf_counter()
        text = text.strip()
        if not text:
            return Result(error="请输入要翻译的内容")
        self.ready.wait()

        def done(value: str, route: str) -> Result:
            return Result(value, route, (time.perf_counter() - start) * 1000)

        mine = self.phrasebook.get(text)
        if mine:
            return done(mine, "phrasebook")
        cached = self.cache.get(text) if self.cache else None
        if cached:
            return done(cached, "cache")
        env = {"DEEPSEEK_API_KEY": self.settings.api_key, "CW_TRANSLATION_MODEL": self.settings["model"]}
        try:
            result = ft.translate(text, mode="chat_short", environ=env, client=self.client,
                                  generation_timeout=float(self.settings["timeout_s"]))
        except ft.TranslationError as error:
            return Result(error=friendly_error(error), ms=(time.perf_counter() - start) * 1000)
        except Exception as error:  # Never let the window die on an unexpected failure.
            return Result(error=f"翻译失败：{type(error).__name__}", ms=(time.perf_counter() - start) * 1000)
        if result["route"] == "generation":
            self._last_network = time.monotonic()
            if self.cache:
                self.cache.put(text, result["short"])
        return done(result["short"], result["route"])

    def test_key(self, key: str) -> str:
        """Empty string when the key works, otherwise a Chinese error message."""
        try:
            if not key.strip():
                return "请先填写 DeepSeek Key"
            from settings import validate_api_key
            validate_api_key(key)
            ft.generate("测试", "", "zh_en", "short", [], {}, {}, key.strip(), self.settings["model"],
                        float(self.settings["timeout_s"]), client=self.client, chat=True)
            return ""
        except ft.TranslationError as error:
            return friendly_error(error)
        except ValueError:
            return "Key 格式不正确，请重新复制完整 Key（不要带空格或换行）"
        except Exception:
            return "Key 测试失败，请检查设置和网络后重试"

    def remember(self, zh: str, en: str) -> None:
        self.phrasebook.remember(zh, en)
        if self.cache:
            self.cache.forget(zh)
