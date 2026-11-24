"""Quran corpus as one continuous token stream.

The whole Quran is laid out as a single sequence of word ids. Ayahs within a
surah are adjacent, so a match can run across consecutive ayahs naturally. A
sentinel is inserted between surahs so no match crosses a surah boundary.

Source data: Tanzil text files in "surah|ayah|text" format
(https://tanzil.net/download/). Use the "Simple" (Imlaei) text for matching;
the Uthmani text is optional and only used for display. The texts are kept
verbatim, as Tanzil's terms require; normalized forms are derived in memory.
"""

from __future__ import annotations

import hashlib
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .store import StoreError, read_store, write_store
from .tanzil import read_tanzil
from .tokenizer import WORD, tokenize
from .uthmani import ACCEPT_COST, REVIEWED_COST, align_ayah, uthmani_keys

SURAH_BREAK = -2
TOTAL_AYAHS = 6236
TOTAL_SURAHS = 114
# Bump when the layout of Corpus changes, so old cache files are ignored.
CACHE_VERSION = 8  # layout of the store (SQLite), see store.py


@dataclass(frozen=True, slots=True)
class Ayah:
    surah: int
    ayah: int
    simple_text: str
    uthmani_text: str | None
    start: int  # first stream position
    end: int  # one past the last stream position

    @property
    def word_count(self) -> int:
        return self.end - self.start


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cache_key(simple_path: str | Path, uthmani_path: str | Path | None, require_complete: bool) -> str:
    h = hashlib.sha256()
    h.update(f"v{CACHE_VERSION}|complete={require_complete}|".encode())
    h.update(Path(simple_path).read_bytes())
    h.update(b"|uthmani|")
    if uthmani_path:
        h.update(Path(uthmani_path).read_bytes())
    return h.hexdigest()


class Corpus:
    def __init__(
        self,
        rows: list[tuple[int, int, str]],
        uthmani: dict[tuple[int, int], str] | None = None,
        source: dict[str, Any] | None = None,
    ):
        self.source = source or {}
        self.vocab: dict[str, int] = {}
        self.vocab_aggressive: list[str] = []
        self.vocab_strict: list[str] = []
        self.stream = array("i")
        self.raw_words: list[str] = []  # original (diacritized) word per position
        self.pos_ayah = array("i")  # ayah index per position, -1 for sentinel
        self.pos_word = array("i")  # 0-based word index within the ayah
        self.ayahs: list[Ayah] = []
        self.ayah_index: dict[tuple[int, int], int] = {}
        self.surah_ayah_count: dict[int, int] = {}

        prev_surah = None
        for surah, ayah, text in rows:
            if prev_surah is not None and surah != prev_surah:
                self._push(SURAH_BREAK, "", -1, -1)
            prev_surah = surah
            start = len(self.stream)
            idx = len(self.ayahs)
            words = [t for t in tokenize(text) if t.kind == WORD]
            for w_i, tok in enumerate(words):
                self._push(self._id(tok.strict, tok.aggressive), tok.raw, idx, w_i)
            self.ayahs.append(
                Ayah(surah, ayah, text, (uthmani or {}).get((surah, ayah)), start, len(self.stream))
            )
            self.ayah_index[(surah, ayah)] = idx
            self.surah_ayah_count[surah] = max(self.surah_ayah_count.get(surah, 0), ayah)

        self._build_index()

        self.has_uthmani = uthmani is not None
        # Uthmani key (STRICT) -> Simple STRICT word(s); keys with two different
        # targets in the Quran are removed (see _build_uthmani).
        self.uthmani_map: dict[str, tuple[str, ...]] = {}
        self.block_text: list[str] = []  # Uthmani text of each aligned block
        self.pos_block = array("i", [-1]) * len(self.stream)  # block id per position
        self.uthmani_suspicious: list[str] = []  # blocks not accepted (not even after review)
        self.uthmani_reviewed: list[str] = []  # 1:1 blocks accepted after review (cost > ACCEPT_COST)
        self.uthmani_collisions = 0
        self.uthmani_reviewed_conflicts = 0
        if uthmani is not None:
            self._build_uthmani()

    # ------------------------------------------------------------------ build
    def _build_uthmani(self) -> None:
        """Align each ayah's Uthmani words to its Simple words (see uthmani.py).

        Two passes decide the lookup dictionary. Exact alignments (cost <=
        ACCEPT_COST) are added first; a key whose exact alignments disagree is
        removed. Reviewed 1:1 blocks (cost up to REVIEWED_COST) only fill keys that
        have no exact entry and do not disagree with each other, so a reviewed
        alignment can never override an exact one.
        """
        strict_of = {i: w for w, i in self.vocab.items()}
        collide: set[str] = set()
        reviewed: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        for ay in self.ayahs:
            if ay.uthmani_text is None:
                continue
            s_words = [strict_of[self.stream[p]] for p in range(ay.start, ay.end)]
            u_words = [w for w in ay.uthmani_text.split() if any(ch.isalpha() for ch in w)]
            label = f"{ay.surah}:{ay.ayah}"
            for b in align_ayah(u_words, s_words):
                if b.u1 == b.u0 or b.s1 == b.s0:
                    self.uthmani_suspicious.append(f"{label} unaligned")
                    continue
                bid = len(self.block_text)
                self.block_text.append(" ".join(u_words[b.u0 : b.u1]))
                for p in range(ay.start + b.s0, ay.start + b.s1):
                    self.pos_block[p] = bid
                size = (b.u1 - b.u0, b.s1 - b.s0)
                # 1:1 and 1:3 blocks up to REVIEWED_COST were reviewed and accepted (the 1:3
                # block is 20:94 «يَبْنَؤُمَّ»); 1:2 blocks keep the stricter ACCEPT_COST
                limit = REVIEWED_COST if size in ((1, 1), (1, 3)) else ACCEPT_COST
                desc = (
                    f"{label} cost={b.cost:.2f} uthmani={self.block_text[bid]!r} "
                    f"simple={' '.join(s_words[b.s0 : b.s1])!r}"
                )
                # 2:1 blocks are not keyed (a dictionary key is one Uthmani word)
                if b.cost > limit or size not in ((1, 1), (1, 2), (1, 3)):
                    self.uthmani_suspicious.append(desc)
                    continue
                target = tuple(s_words[b.s0 : b.s1])
                keys = tuple(sorted(set(uthmani_keys(u_words[b.u0]))))
                if b.cost > ACCEPT_COST:
                    self.uthmani_reviewed.append(desc)
                    reviewed.append((keys, target))
                    continue
                for k in keys:
                    if k in collide:
                        continue
                    prev = self.uthmani_map.get(k)
                    if prev is None:
                        self.uthmani_map[k] = target
                    elif prev != target:
                        collide.add(k)
        for k in collide:
            self.uthmani_map.pop(k, None)
        self.uthmani_collisions = len(collide)

        # reviewed pass: fill only free keys, and only when reviewed entries agree
        pending: dict[str, tuple[str, ...]] = {}
        conflict: set[str] = set()
        for keys, target in reviewed:
            for k in keys:
                if k in self.uthmani_map or k in collide:
                    continue  # an exact alignment (or a removed key) wins
                prev = pending.get(k)
                if prev is None:
                    pending[k] = target
                elif prev != target:
                    conflict.add(k)
        for k, target in pending.items():
            if k not in conflict:
                self.uthmani_map[k] = target
        self.uthmani_reviewed_conflicts = len(conflict)

    def uthmani_text(self, pos: int) -> str:
        """Uthmani words aligned to stream position `pos` ('' if none)."""
        b = self.pos_block[pos]
        return self.block_text[b] if b >= 0 else ""

    def _id(self, strict: str, aggressive: str) -> int:
        i = self.vocab.get(strict)
        if i is None:
            i = len(self.vocab_aggressive)
            self.vocab[strict] = i
            self.vocab_aggressive.append(aggressive)
            self.vocab_strict.append(strict)
        return i

    def _push(self, wid: int, raw: str, ayah_idx: int, word_idx: int) -> None:
        self.stream.append(wid)
        self.raw_words.append(raw)
        self.pos_ayah.append(ayah_idx)
        self.pos_word.append(word_idx)

    def _build_index(self) -> None:
        s = self.stream
        big: dict[tuple[int, int], list[int]] = {}
        tri: dict[tuple[int, int, int], list[int]] = {}
        for p in range(len(s) - 1):
            a, b = s[p], s[p + 1]
            if a < 0 or b < 0:
                continue
            big.setdefault((a, b), []).append(p)
            if p + 2 < len(s) and s[p + 2] >= 0:
                tri.setdefault((a, b, s[p + 2]), []).append(p)
        self.bigrams = {k: array("i", v) for k, v in big.items()}
        self.trigrams = {k: array("i", v) for k, v in tri.items()}

    # ------------------------------------------------------------ constructors
    @classmethod
    def from_tanzil(
        cls,
        simple_path: str | Path,
        uthmani_path: str | Path | None = None,
        require_complete: bool = True,
        cache_dir: str | Path | None = None,
    ) -> Corpus:
        """Build a corpus from Tanzil files.

        With `cache_dir`, the built corpus is stored there as a SQLite file under a
        key that is the SHA-256 of the input bytes (and the cache version). Editing a
        Tanzil file gives a new key, so the old store is never used. A store that
        cannot be read is rebuilt. The store is plain data (no pickle), so loading it
        runs no code.
        """
        if cache_dir is None:
            return cls._build_from_tanzil(simple_path, uthmani_path, require_complete)
        key = _cache_key(simple_path, uthmani_path, require_complete)
        path = Path(cache_dir) / f"corpus-{key}.sqlite"
        try:
            return cls._from_parts(read_store(path, str(CACHE_VERSION), key))
        except (StoreError, KeyError, TypeError, ValueError):
            pass  # missing, stale or corrupt: rebuild below
        corpus = cls._build_from_tanzil(simple_path, uthmani_path, require_complete)
        write_store(path, {"cache_version": str(CACHE_VERSION), "cache_key": key}, corpus.to_parts())
        return corpus

    def to_parts(self) -> dict[str, Any]:
        """The built corpus as plain values (JSON-able, or arrays). The indexes are
        not included: `_from_parts` rebuilds them, which is cheap."""
        return {
            "source": self.source,
            "vocab": self.vocab,
            "vocab_aggressive": self.vocab_aggressive,
            "vocab_strict": self.vocab_strict,
            "raw_words": self.raw_words,
            "stream": self.stream,
            "pos_ayah": self.pos_ayah,
            "pos_word": self.pos_word,
            "ayahs": [asdict(a) for a in self.ayahs],
            "ayah_index": [[s, a, i] for (s, a), i in self.ayah_index.items()],
            "surah_ayah_count": {str(k): v for k, v in self.surah_ayah_count.items()},
            "has_uthmani": self.has_uthmani,
            "uthmani_map": {k: list(v) for k, v in self.uthmani_map.items()},
            "block_text": self.block_text,
            "pos_block": self.pos_block,
            "uthmani_suspicious": self.uthmani_suspicious,
            "uthmani_reviewed": self.uthmani_reviewed,
            "uthmani_collisions": self.uthmani_collisions,
            "uthmani_reviewed_conflicts": self.uthmani_reviewed_conflicts,
        }

    @classmethod
    def _from_parts(cls, parts: dict[str, Any]) -> Corpus:
        """Rebuild a corpus from `to_parts()` output (see store.read_store)."""
        obj = cls.__new__(cls)
        obj.source = dict(parts["source"])
        obj.vocab = dict(parts["vocab"])
        obj.vocab_aggressive = list(parts["vocab_aggressive"])
        obj.vocab_strict = list(parts["vocab_strict"])
        obj.raw_words = list(parts["raw_words"])
        obj.stream = parts["stream"]
        obj.pos_ayah = parts["pos_ayah"]
        obj.pos_word = parts["pos_word"]
        obj.ayahs = [Ayah(**a) for a in parts["ayahs"]]
        obj.ayah_index = {(s, a): i for s, a, i in parts["ayah_index"]}
        obj.surah_ayah_count = {int(k): v for k, v in parts["surah_ayah_count"].items()}
        obj.has_uthmani = bool(parts["has_uthmani"])
        obj.uthmani_map = {k: tuple(v) for k, v in parts["uthmani_map"].items()}
        obj.block_text = list(parts["block_text"])
        obj.pos_block = parts["pos_block"]
        obj.uthmani_suspicious = list(parts["uthmani_suspicious"])
        obj.uthmani_reviewed = list(parts["uthmani_reviewed"])
        obj.uthmani_collisions = int(parts["uthmani_collisions"])
        obj.uthmani_reviewed_conflicts = int(parts["uthmani_reviewed_conflicts"])
        if len(obj.pos_block) != len(obj.stream) or len(obj.pos_ayah) != len(obj.stream):
            raise ValueError("array lengths disagree")
        obj._build_index()
        return obj

    @classmethod
    def _build_from_tanzil(
        cls,
        simple_path: str | Path,
        uthmani_path: str | Path | None,
        require_complete: bool,
    ) -> Corpus:
        simple_path = Path(simple_path)
        rows = read_tanzil(simple_path)
        source = {"simple_file": simple_path.name, "simple_sha256": _sha256(simple_path)}
        uthmani = None
        if uthmani_path:
            uthmani_path = Path(uthmani_path)
            u_rows = read_tanzil(uthmani_path)
            if [(s, a) for s, a, _ in u_rows] != [(s, a) for s, a, _ in rows]:
                raise ValueError("Uthmani and Simple files do not have the same ayah list")
            uthmani = {(s, a): t for s, a, t in u_rows}
            source |= {"uthmani_file": uthmani_path.name, "uthmani_sha256": _sha256(uthmani_path)}
        if require_complete:
            surahs = {s for s, _, _ in rows}
            if len(rows) != TOTAL_AYAHS or len(surahs) != TOTAL_SURAHS:
                raise ValueError(
                    f"Expected {TOTAL_AYAHS} ayahs in {TOTAL_SURAHS} surahs, got "
                    f"{len(rows)} ayahs in {len(surahs)} surahs. "
                    "Pass require_complete=False for partial test corpora."
                )
        source["attribution"] = "Quran text: Tanzil Project (https://tanzil.net)"
        return cls(rows, uthmani, source)

    # ----------------------------------------------------------------- lookup
    def word_id(self, strict: str) -> int:
        return self.vocab.get(strict, -1)

    def find_all(self, seq: list[int]) -> list[int]:
        """All stream positions where the id sequence occurs (len >= 2)."""
        if len(seq) < 2:
            raise ValueError("sequence must have at least 2 words")
        if len(seq) >= 3:
            starts = self.trigrams.get((seq[0], seq[1], seq[2]), ())
        else:
            starts = self.bigrams.get((seq[0], seq[1]), ())
        n, s = len(seq), self.stream
        return [p for p in starts if p + n <= len(s) and all(s[p + k] == seq[k] for k in range(n))]

    def refs(self, start: int, end: int) -> list[tuple[int, int, int, int]]:
        """Stream range -> [(surah, ayah, word_start, word_end)], 1-based inclusive words."""
        out: list[list[int]] = []
        for p in range(start, end):
            a = self.pos_ayah[p]
            if a < 0:
                continue
            ay = self.ayahs[a]
            w = self.pos_word[p] + 1
            if out and out[-1][0] == ay.surah and out[-1][1] == ay.ayah:
                out[-1][3] = w
            else:
                out.append([ay.surah, ay.ayah, w, w])
        return [(r[0], r[1], r[2], r[3]) for r in out]

    def covers_full_ayahs(self, start: int, end: int) -> bool:
        first, last = self.pos_ayah[start], self.pos_ayah[end - 1]
        return self.ayahs[first].start == start and self.ayahs[last].end == end

    def __len__(self) -> int:
        return len(self.ayahs)
