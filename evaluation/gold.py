"""Gold file reader for the evaluation harness.

One JSON document per line:
  {"id", "text", "source": "synthetic|llm|ocr|manual",
   "spans": [{"start", "end", "status", "locations": [[["s","a","w1","w2"],...]],
              "intended": true}]}
A document with "spans": [] is a negative.
"""

from __future__ import annotations

import json
from pathlib import Path

from .metrics import Doc, Span

GOLD_STATUSES = {"verified", "ambiguous", "altered", "spliced", "candidate"}
GOLD_SOURCES = {"synthetic", "llm", "ocr", "manual"}


class GoldFormatError(ValueError):
    pass


def _locations(raw, where: str) -> tuple:
    if not isinstance(raw, list):
        raise GoldFormatError(f"{where}: locations must be a list")
    out = []
    for loc in raw:
        if not isinstance(loc, list) or not loc:
            raise GoldFormatError(f"{where}: each location must be a non-empty list")
        refs = []
        for r in loc:
            if not isinstance(r, list) or len(r) != 4 or not all(isinstance(x, int) for x in r):
                raise GoldFormatError(f"{where}: each ref must be [surah, ayah, w1, w2] of ints")
            refs.append(tuple(r))
        out.append(tuple(refs))
    return tuple(out)


def load_gold(path: str | Path) -> list[Doc]:
    docs: list[Doc] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            if not line.strip():
                continue
            where = f"{path}:{ln}"
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GoldFormatError(f"{where}: invalid JSON ({exc})") from exc
            for key in ("id", "text", "source", "spans"):
                if key not in obj:
                    raise GoldFormatError(f"{where}: missing key {key!r}")
            if obj["id"] in seen:
                raise GoldFormatError(f"{where}: duplicate id {obj['id']!r}")
            seen.add(obj["id"])
            if obj["source"] not in GOLD_SOURCES:
                raise GoldFormatError(f"{where}: unknown source {obj['source']!r}")
            text = obj["text"]
            spans = []
            for k, s in enumerate(obj["spans"]):
                sw = f"{where} span {k}"
                if s.get("status") not in GOLD_STATUSES:
                    raise GoldFormatError(f"{sw}: unknown status {s.get('status')!r}")
                if not (0 <= s["start"] < s["end"] <= len(text)):
                    raise GoldFormatError(f"{sw}: offsets outside the text")
                spans.append(
                    Span(
                        doc_id=obj["id"],
                        start=s["start"],
                        end=s["end"],
                        status=s["status"],
                        locations=_locations(s.get("locations", []), sw),
                        intended=bool(s.get("intended", True)),
                        kind=str(s.get("kind", "")),
                    )
                )
            docs.append(Doc(obj["id"], text, obj["source"], spans))
    return docs
