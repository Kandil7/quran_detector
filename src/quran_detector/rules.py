"""Optional token-level rules for LLM and OCR text (task 07).

Each rule is switched on by its own Config flag and is off by default:

  join_conjunctions  «و الله» → «والله», «ف الله» → «فالله». A standalone و or ف is
                     joined to the next word when the joined form exists in the
                     corpus and the split pair does not occur in the Quran stream.
  join_lam           «ل الله» → «لله» (the alef of الله is dropped in «لله»), and
                     «ل» + word → «ل» + word when that form exists.
  split_merged       an unknown word such as «ياأيها» or «انشاء» is split into two
                     known words when the pair occurs in the Quran stream. The two
                     pieces share the offsets of the original word.

Rules work on the token list only; the text is never changed, and every
returned token still refers to a span of the original text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .corpus import Corpus
from .normalizer import Level, normalize
from .tokenizer import WORD, Token

if TYPE_CHECKING:
    from .detector import Config

CONJUNCTIONS = ("و", "ف")
LAM = "ل"


def _pair_in_stream(corpus: Corpus, a: str, b: str) -> bool:
    ia, ib = corpus.word_id(a), corpus.word_id(b)
    return ia >= 0 and ib >= 0 and (ia, ib) in corpus.bigrams


def _join_pair(text: str, a: Token, b: Token, strict: str) -> Token:
    return Token(
        a.start,
        b.end,
        text[a.start : b.end],
        strict,
        normalize(strict, Level.AGGRESSIVE),
        WORD,
    )


def join_prefixes(
    text: str, tokens: list[Token], corpus: Corpus, prefixes: tuple[str, ...], lam: bool
) -> list[Token]:
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if t.kind == WORD and t.strict in prefixes and nxt is not None and nxt.kind == WORD:
            forms = [t.strict + nxt.strict]
            if lam and nxt.strict.startswith("ال") and len(nxt.strict) > 2:
                forms.insert(0, t.strict + nxt.strict[2:])  # ل + الله → لله
            chosen = next((f for f in forms if corpus.word_id(f) >= 0), None)
            if chosen and not _pair_in_stream(corpus, t.strict, nxt.strict):
                out.append(_join_pair(text, t, nxt, chosen))
                i += 2
                continue
        out.append(t)
        i += 1
    return out


def split_unknown(text: str, tokens: list[Token], corpus: Corpus) -> list[Token]:
    out: list[Token] = []
    for t in tokens:
        if t.kind == WORD and len(t.strict) >= 4 and corpus.word_id(t.strict) < 0:
            cut = None
            for k in range(2, len(t.strict) - 1):
                if _pair_in_stream(corpus, t.strict[:k], t.strict[k:]):
                    cut = k
                    break
            if cut is not None:
                for part in (t.strict[:cut], t.strict[cut:]):
                    out.append(Token(t.start, t.end, t.raw, part, normalize(part, Level.AGGRESSIVE), WORD))
                continue
        out.append(t)
    return out


def apply_token_rules(text: str, tokens: list[Token], corpus: Corpus, cfg: Config) -> list[Token]:
    """Apply the enabled rules in a fixed order. Returns the list unchanged if none is on."""
    if cfg.join_conjunctions:
        tokens = join_prefixes(text, tokens, corpus, CONJUNCTIONS, lam=False)
    if cfg.join_lam:
        tokens = join_prefixes(text, tokens, corpus, (LAM,), lam=True)
    if cfg.split_merged:
        tokens = split_unknown(text, tokens, corpus)
    return tokens
