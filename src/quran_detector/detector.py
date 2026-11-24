"""Deterministic Quran quote detection, grounding and verification.

Pipeline
  1. Tokenize the input (offsets kept) and map words to corpus ids (STRICT).
  2. Seed: look up every input bigram (trigram for very frequent bigrams) in
     the index over the continuous Quran stream.
  3. Extend: grow each seed into a maximal exact match (MEM) along the stream.
     MEMs cross ayah boundaries freely, never surah boundaries.
  4. Chain: join MEMs separated by small gaps (<= max_gap words on both sides)
     into one alignment. Gaps become variant/substitute/insert/delete ops.
  5. Select: weighted interval scheduling picks the best non-overlapping spans.
  6. Ground: an exact span is looked up again in the whole corpus so every
     location is reported (repeated phrases -> ambiguous).
  7. Decide: explicit gates set the status; nothing is "verified" on score.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, replace

from .citations import find_citation
from .corpus import Corpus
from .diacritics import compare as compare_diacritics
from .metadata import QuranMetadata
from .models import DetectionResult, DiffOp, QuranMatch, Ref, Status
from .normalizer import Level, normalize_phrase
from .ocr import resolve_ocr
from .rules import apply_token_rules
from .tokenizer import BARRIER, Token, tokenize
from .uthmani import resolve_tokens
from .variants import orth_variant

UNKNOWN = -1
BARRIER_ID = -3

_CONTEXT_MARKERS = [
    normalize_phrase(m, Level.AGGRESSIVE)
    for m in [
        "قال تعالى",
        "قوله تعالى",
        "تعالى",
        "قال الله",
        "يقول الله",
        "سبحانه",
        "عز وجل",
        "جل جلاله",
        "جل وعلا",
        "في كتابه",
        "في محكم",
        "الآية",
        "القرآن",
        "التنزيل",
    ]
]

# Everyday expressions that are also Quran text. Never "verified" without context.
_FORMULAIC = {
    normalize_phrase(p, Level.STRICT)
    for p in [
        "بسم الله الرحمن الرحيم",
        "الحمد لله رب العالمين",
        "إنا لله وإنا إليه راجعون",
        "حسبنا الله ونعم الوكيل",
        "لا إله إلا الله",
        "ما شاء الله لا قوة إلا بالله",
        "إن شاء الله",
        "ما شاء الله",
        "سبحان الله",
        "الحمد لله",
        "في سبيل الله",
        "إن الله غفور رحيم",
        "والله أعلم",
        "إن الله على كل شيء قدير",
        "رب العالمين",
        "لا قوة إلا بالله",
        "الله أكبر",
        "استغفر الله",
    ]
}

_OPEN_CLOSE = [("﴿", "﴾"), ("«", "»"), ("“", "”"), ('"', '"')]


@dataclass(frozen=True)
class Config:
    min_words: int = 5  # exact span verified without context
    min_words_with_context: int = 3  # exact span verified with context
    min_candidate_words: int = 3  # shorter exact spans are dropped
    max_gap: int = 3  # unmatched words bridged inside one quote
    min_altered_matched: int = 5
    min_altered_ratio: float = 0.6
    frequent_bigram: int = 300  # above this, seed with trigrams
    context_window: int = 40
    citation_window: int = 60
    include_candidates: bool = False
    # "off": ignore diacritics (default). "report": compare marks written by the
    # writer and set diacritics_ok / diff ops, status unchanged. "strict": as
    # report, and a verified match with a wrong mark becomes altered.
    diacritics: str = "off"
    # Token rules for LLM/OCR text (see rules.py). Each is independent, default off.
    uthmani: bool = True  # resolve Uthmani spellings when the corpus has an Uthmani file
    # Quotation context markers (e.g. «قال تعالى») count only in the last 6 words of the
    # same sentence. On by default: on the 3,000-document synthetic test set it removes
    # verified false matches and false-match negative documents (see README, Evaluation).
    strict_context: bool = True
    # "exact": the default. "ocr": words without an exact match are corrected to the
    # nearest Quran word (see ocr.py) and matches that use one are `needs_review`.
    mode: str = "exact"
    ocr_max_edits: float = 2.0
    # Narrow orthographic variants count as `variant` (not an edit), see variants.py.
    # Off until evaluated: a variant does not block `verified`.
    orth_variants: bool = False
    join_conjunctions: bool = False  # «و الله» → «والله»
    join_lam: bool = False  # «ل الله» → «لله»
    split_merged: bool = False  # «ياأيها» → «يا أيها»

    def __post_init__(self) -> None:
        if self.mode not in ("exact", "ocr"):
            raise ValueError(f"mode must be 'exact' or 'ocr', got {self.mode!r}")
        if self.diacritics not in ("off", "report", "strict"):
            raise ValueError(f"diacritics must be 'off', 'report' or 'strict', got {self.diacritics!r}")


HIGH_PRECISION = Config()
BALANCED = Config(include_candidates=True, min_words=4)


@dataclass
class _Region:
    s: int  # input token range [s, e)
    e: int
    sp: int  # corpus stream range [sp, ep)
    ep: int
    weight: float
    chain: list[tuple[int, int, int]]


class QuranDetector:
    def __init__(
        self,
        corpus: Corpus,
        config: Config = HIGH_PRECISION,
        metadata: QuranMetadata | None = None,
    ):
        self.corpus = corpus
        self.cfg = config
        # Metadata only describes locations in the output. It never affects matching.
        self.metadata = metadata

    # ================================================================ public
    def detect(self, text: str, assume_quote: bool = False) -> DetectionResult:
        tokens = apply_token_rules(text, tokenize(text), self.corpus, self.cfg)
        if self.cfg.uthmani and self.corpus.has_uthmani:
            tokens = resolve_tokens(tokens, self.corpus)
        if self.cfg.mode == "ocr":
            tokens = resolve_ocr(tokens, self.corpus, self.cfg.ocr_max_edits)
        ids = [BARRIER_ID if t.kind == BARRIER else self.corpus.word_id(t.strict) for t in tokens]
        mems = self._find_mems(ids)
        regions = self._chain(mems, tokens)
        selected = self._select(regions)

        matches: list[QuranMatch] = []
        spans: list[tuple[int, int, int, int]] = []
        for reg, alts in selected:
            reg = self._extend_variants(reg, ids, tokens)
            m = self._build_match(text, tokens, ids, reg, alts, assume_quote)
            if m is not None:
                matches.append(m)
                spans.append((reg.s, reg.e, reg.sp, reg.ep))

        self._mark_spliced(text, matches, spans)
        if not self.cfg.include_candidates:
            keep = [i for i, m in enumerate(matches) if m.status is not Status.CANDIDATE]
            remap = {old: new for new, old in enumerate(keep)}
            matches = [matches[i] for i in keep]
            for m in matches:
                m.spliced_with = [remap[j] for j in m.spliced_with if j in remap]
        source = dict(self.corpus.source)
        if self.metadata is not None and self.metadata.file_sha256:
            source["metadata_sha256"] = self.metadata.file_sha256
        return DetectionResult(text, matches, source)

    def verify(self, quote: str) -> QuranMatch | None:
        """Check a string the caller asserts is a Quran quote.

        Returns the match covering most of the quote, or None. Compare
        `match.text` with the input to see whether the whole quote matched.
        """
        cfg = self.cfg
        self.cfg = replace(cfg, include_candidates=True)
        try:
            res = self.detect(quote, assume_quote=True)
        finally:
            self.cfg = cfg
        if not res.matches:
            return None
        return max(res.matches, key=lambda m: m.word_count)

    # ======================================================== seed + extend
    def _find_mems(self, ids: list[int]) -> list[tuple[int, int, int]]:
        c, cfg = self.corpus, self.cfg
        s, S, n = c.stream, len(c.stream), len(ids)
        mems = []
        for i in range(n - 1):
            a, b = ids[i], ids[i + 1]
            if a < 0 or b < 0:
                continue
            starts = c.bigrams.get((a, b))
            if not starts:
                continue
            if len(starts) > cfg.frequent_bigram:
                if i + 2 >= n or ids[i + 2] < 0:
                    continue
                starts = c.trigrams.get((a, b, ids[i + 2]))
                if not starts:
                    continue
            prev = ids[i - 1] if i > 0 else UNKNOWN
            for p in starts:
                if prev >= 0 and p > 0 and s[p - 1] == prev:
                    continue  # not left-maximal; found from an earlier seed
                L = 2
                while i + L < n and p + L < S and ids[i + L] == s[p + L]:
                    L += 1
                mems.append((i, p, L))
        return mems

    # ================================================================ chain
    def _surah_of(self, pos: int) -> int:
        return self.corpus.ayahs[self.corpus.pos_ayah[pos]].surah

    def _chain(self, mems: list[tuple[int, int, int]], tokens: list[Token]) -> list[_Region]:
        if not mems:
            return []
        G = self.cfg.max_gap
        best = [0.0] * len(mems)
        back = [-1] * len(mems)
        by_end: dict[int, list[int]] = {}  # input end index -> mem indices
        for k, (bi, bp, bl) in enumerate(mems):
            best[k] = float(bl)
            preds = [j for e in range(bi - G, bi + 1) for j in by_end.get(e, ())]
            by_end.setdefault(bi + bl, []).append(k)
            for j in preds:
                ai, ap, al = mems[j]
                gi, gp = bi - (ai + al), bp - (ap + al)
                if not (0 <= gi <= G and 0 <= gp <= G) or (gi == 0 and gp == 0):
                    continue
                gap = max(gi, gp)
                if gap > 1 and (al < 3 or bl < 3):
                    continue  # don't bridge wide gaps with tiny anchors
                if self._surah_of(ap) != self._surah_of(bp):
                    continue
                if any(tokens[t].kind == BARRIER for t in range(ai + al, bi)):
                    continue
                cand = best[j] + bl + 1 - 0.25 * gap
                if cand > best[k]:
                    best[k], back[k] = cand, j
        regions = []
        for k in range(len(mems)):
            chain, j = [], k
            while j != -1:
                chain.append(mems[j])
                j = back[j]
            chain.reverse()
            first, last = chain[0], chain[-1]
            regions.append(_Region(first[0], last[0] + last[2], first[1], last[1] + last[2], best[k], chain))
        return regions

    # =============================================================== select
    @staticmethod
    def _select(regions: list[_Region]) -> list[tuple[_Region, list[_Region]]]:
        """Weighted interval scheduling over input spans; ties -> alternatives."""
        if not regions:
            return []
        groups: dict[tuple[int, int, float], list[_Region]] = {}
        for r in regions:
            groups.setdefault((r.s, r.e, round(r.weight, 6)), []).append(r)
        reps = sorted(groups.values(), key=lambda g: (g[0].e, g[0].s))
        ends = [g[0].e for g in reps]
        dp = [0.0] * (len(reps) + 1)
        take = [False] * len(reps)
        prev_idx = []
        for k, g in enumerate(reps):
            p = bisect.bisect_right(ends, g[0].s, 0, k)
            prev_idx.append(p)
            with_k = dp[p] + g[0].weight
            if with_k > dp[k]:
                dp[k + 1], take[k] = with_k, True
            else:
                dp[k + 1] = dp[k]
        out, k = [], len(reps) - 1
        while k >= 0:
            if take[k]:
                g = sorted(reps[k], key=lambda r: r.sp)
                out.append((g[0], g[1:]))
                k = prev_idx[k] - 1
            else:
                k -= 1
        out.reverse()
        return out

    # ====================================================== edge variants
    def _variant_eq(self, tok: Token, ids_i: int, pos: int) -> bool:
        c = self.corpus
        wid = c.stream[pos]
        if wid < 0 or tok.kind == BARRIER:
            return False
        if ids_i == wid or tok.aggressive == c.vocab_aggressive[wid]:
            return True
        return self.cfg.orth_variants and orth_variant(tok.strict, c.vocab_strict[wid])

    def _extend_variants(self, reg: _Region, ids: list[int], tokens: list[Token]) -> _Region:
        c = self.corpus
        s, e, sp, ep = reg.s, reg.e, reg.sp, reg.ep
        surah = self._surah_of(sp)
        while (
            e < len(ids)
            and ep < len(c.stream)
            and c.stream[ep] >= 0
            and self._surah_of(ep) == surah
            and self._variant_eq(tokens[e], ids[e], ep)
        ):
            e, ep = e + 1, ep + 1
        while (
            s > 0
            and sp > 0
            and c.stream[sp - 1] >= 0
            and self._surah_of(sp - 1) == surah
            and self._variant_eq(tokens[s - 1], ids[s - 1], sp - 1)
        ):
            s, sp = s - 1, sp - 1
        return replace(reg, s=s, e=e, sp=sp, ep=ep)

    # ============================================================== align
    def _align(
        self, tokens: list[Token], ids: list[int], s: int, e: int, sp: int, ep: int
    ) -> list[tuple[str, int | None, int | None]]:
        """Word-level edit alignment. Returns (op, input_idx, corpus_pos)."""
        c = self.corpus
        A = list(range(s, e))
        B = list(range(sp, ep))
        n, m = len(A), len(B)

        def cost(i: int, j: int) -> float:
            if ids[A[i]] == c.stream[B[j]]:
                return 0.0
            if self._variant_eq(tokens[A[i]], ids[A[i]], B[j]):
                return 0.1
            return 1.0

        INF = float("inf")
        D = [[INF] * (m + 1) for _ in range(n + 1)]
        D[0][0] = 0.0
        for i in range(n + 1):
            for j in range(m + 1):
                if i < n:
                    D[i + 1][j] = min(D[i + 1][j], D[i][j] + 1)
                if j < m:
                    D[i][j + 1] = min(D[i][j + 1], D[i][j] + 1)
                if i < n and j < m:
                    D[i + 1][j + 1] = min(D[i + 1][j + 1], D[i][j] + cost(i, j))
        ops: list[tuple[str, int | None, int | None]] = []
        i, j = n, m
        while i > 0 or j > 0:
            if i > 0 and j > 0 and abs(D[i][j] - (D[i - 1][j - 1] + cost(i - 1, j - 1))) < 1e-9:
                k = cost(i - 1, j - 1)
                op = "equal" if k == 0 else "variant" if k < 1 else "substitute"
                ops.append((op, A[i - 1], B[j - 1]))
                i, j = i - 1, j - 1
            elif i > 0 and abs(D[i][j] - (D[i - 1][j] + 1)) < 1e-9:
                ops.append(("insert", A[i - 1], None))
                i -= 1
            else:
                ops.append(("delete", None, B[j - 1]))
                j -= 1
        ops.reverse()
        return ops

    # ============================================================== build
    def _has_context(self, text: str, start: int, end: int) -> bool:
        before = text[max(0, start - self.cfg.context_window) : start]
        after = text[end : end + self.cfg.context_window]
        b, a = before.rstrip(), after.lstrip()
        for o, cl in _OPEN_CLOSE:
            if b.endswith(o) and a.startswith(cl):
                return True
        if b.endswith("﴿") or a.startswith("﴾"):
            return True
        if self.cfg.strict_context:
            # only the last few words of the same sentence can introduce a quote
            sentence = re.split(r"[.!?\xd8\x9f\n]", before)[-1]
            before = " ".join(sentence.split()[-6:])
        before_n = normalize_phrase(re.sub(r"[^\w\s]", " ", before), Level.AGGRESSIVE)
        return any(mk in before_n for mk in _CONTEXT_MARKERS)

    def _build_match(
        self,
        text: str,
        tokens: list[Token],
        ids: list[int],
        reg: _Region,
        alts: list[_Region],
        assume_quote: bool,
    ) -> QuranMatch | None:
        c, cfg = self.corpus, self.cfg
        ops = self._align(tokens, ids, reg.s, reg.e, reg.sp, reg.ep)
        n_words = reg.e - reg.s
        matched = sum(1 for o in ops if o[0] in ("equal", "variant"))
        edits = [o for o in ops if o[0] in ("substitute", "insert", "delete")]
        start_char, end_char = tokens[reg.s].start, tokens[reg.e - 1].end
        ctx = assume_quote or self._has_context(text, start_char, end_char)
        full_ayahs = c.covers_full_ayahs(reg.sp, reg.ep)

        # ---- grounding: every location of the same words
        if not edits:
            seq = list(c.stream[reg.sp : reg.ep])
            starts = c.find_all(seq) if len(seq) >= 2 else [reg.sp]
            starts = sorted(set(starts) | {reg.sp})
            loc_ranges = [(p, p + len(seq)) for p in starts]
        else:
            loc_ranges = [(reg.sp, reg.ep)] + [(r.sp, r.ep) for r in alts]
        locations = [[Ref(*r) for r in c.refs(a, b)] for a, b in loc_ranges]

        # ---- citation given by the writer
        nxt = text[end_char : end_char + cfg.citation_window]
        cit = find_citation(nxt)
        claimed, cit_ok = None, None
        if cit:
            claimed = f"{cit.surah}:{cit.ayah_start}" + (
                f"-{cit.ayah_end}" if cit.ayah_end != cit.ayah_start else ""
            )
            consistent = [
                k
                for k, loc in enumerate(locations)
                if cit.covers(loc[0].surah, loc[0].ayah) and cit.covers(loc[-1].surah, loc[-1].ayah)
            ]
            cit_ok = bool(consistent)
            if consistent and len(locations) > 1:
                locations = [locations[k] for k in consistent]
                loc_ranges = [loc_ranges[k] for k in consistent]
            ctx = True

        # ---- gates
        phrase = " ".join(tokens[i].strict for i in range(reg.s, reg.e))
        if not edits:
            if n_words < cfg.min_candidate_words and not (ctx and full_ayahs):
                return None
            strong = (
                n_words >= cfg.min_words
                or (ctx and n_words >= cfg.min_words_with_context)
                or (ctx and full_ayahs)
            )
            if phrase in _FORMULAIC and not ctx:
                status = Status.CANDIDATE
            elif len(locations) > 1:
                status = Status.AMBIGUOUS if strong else Status.CANDIDATE
            else:
                status = Status.VERIFIED if strong else Status.CANDIDATE
        else:
            ratio = matched / max(n_words, reg.ep - reg.sp)
            if matched >= cfg.min_altered_matched and ratio >= cfg.min_altered_ratio:
                status = Status.ALTERED
            elif ctx and matched >= cfg.min_words_with_context:
                status = Status.CANDIDATE
            else:
                return None

        # a match is "uthmani" when any of its input words was resolved from Uthmani
        # spelling; then all references (diff and diacritics) are Uthmani words
        script = "uthmani" if any(tokens[i].uthmani for i in range(reg.s, reg.e)) else "simple"
        uth = script == "uthmani"
        dia_diff: list[DiffOp] = []
        dia_ok: bool | None = None
        if cfg.diacritics != "off":
            dia_diff, dia_ok = self._diacritic_check(tokens, ops, uth)
            if cfg.diacritics == "strict" and dia_diff and status is Status.VERIFIED:
                status = Status.ALTERED

        # OCR-corrected words: a match that uses one is never verified
        if any(tokens[i].ocr for i in range(reg.s, reg.e)) and status in (
            Status.VERIFIED,
            Status.AMBIGUOUS,
            Status.ALTERED,
        ):
            status = Status.NEEDS_REVIEW

        sp, ep = loc_ranges[0]
        diff = []
        for op, ii, pp in ops:
            if op == "equal":
                continue
            tok = tokens[ii] if ii is not None else None
            diff.append(
                DiffOp(
                    op,
                    tok.raw if tok else None,
                    self._expected_word(uth, pp) if pp is not None else None,
                    tok.start if tok else None,
                    tok.end if tok else None,
                )
            )
        diff.extend(dia_diff)
        ayah_ids = sorted({c.pos_ayah[p] for p in range(sp, ep) if c.pos_ayah[p] >= 0})
        if script == "uthmani":
            uthmani = self._uthmani_refs(sp, ep)
        else:
            uthmani = [t for a in ayah_ids if (t := c.ayahs[a].uthmani_text)]
        coverage = matched / max(n_words, reg.ep - reg.sp)
        score = round(coverage * min(1.0, n_words / 8) * (1.0 if not edits else 0.8), 4)

        return QuranMatch(
            start_char=start_char,
            end_char=end_char,
            text=text[start_char:end_char],
            status=status,
            locations=locations,
            word_count=n_words,
            matched_words=matched,
            score=score,
            diff=diff,
            reference_text=" ".join(c.raw_words[sp:ep]),
            reference_uthmani=uthmani,
            has_context=ctx,
            claimed_ref=claimed,
            citation_correct=cit_ok,
            diacritics_ok=dia_ok,
            script=script,
            location_meta=([self.metadata.location_meta(loc) for loc in locations] if self.metadata else []),
        )

    def _expected_word(self, uth: bool, pp: int) -> str:
        """Reference word of a diff op: the Uthmani word for an Uthmani match."""
        if uth:
            return self.corpus.uthmani_text(pp) or self.corpus.raw_words[pp]
        return self.corpus.raw_words[pp]

    def _uthmani_refs(self, sp: int, ep: int) -> list[str]:
        out: list[str] = []
        prev = -1
        for p in range(sp, ep):
            b = self.corpus.pos_block[p]
            if b >= 0 and b != prev:
                out.append(self.corpus.block_text[b])
                prev = b
        return out

    def _diacritic_check(
        self, tokens: list[Token], ops: list[tuple[str, int | None, int | None]], uth: bool
    ) -> tuple[list[DiffOp], bool | None]:
        """Compare marks of matched words with the reference.

        Returns (diacritic diff ops, diacritics_ok). diacritics_ok is None when no
        word had marks that could be compared.
        """
        out: list[DiffOp] = []
        checked = False
        for op, ii, pp in ops:
            if op not in ("equal", "variant") or ii is None or pp is None:
                continue
            tok = tokens[ii]
            ref = self._expected_word(uth, pp)
            did, errs = compare_diacritics(tok.raw, ref)
            checked = checked or did
            for idx in errs:
                out.append(DiffOp("diacritic", tok.raw, ref, tok.start, tok.end, idx))
        return out, (None if not checked else not out)

    # ============================================================= splice
    def _mark_spliced(
        self, text: str, matches: list[QuranMatch], spans: list[tuple[int, int, int, int]]
    ) -> None:
        for k in range(len(matches) - 1):
            m1, m2 = matches[k], matches[k + 1]
            s1, s2 = spans[k], spans[k + 1]
            if s2[0] != s1[1] or s1[3] == s2[2]:
                continue  # words in between, or the Quran text simply continues
            between = text[m1.end_char : m2.start_char]
            if any(ch in between for ch in '﴾﴿«»"“”'):
                continue  # two separately quoted passages
            if min(m1.word_count, m2.word_count) < self.cfg.min_words_with_context:
                continue
            for a, b in ((m1, k + 1), (m2, k)):
                a.spliced_with.append(b)
                if a.status not in (Status.CANDIDATE, Status.NEEDS_REVIEW):
                    a.status = Status.SPLICED
