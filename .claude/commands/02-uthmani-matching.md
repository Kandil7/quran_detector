# Task: match input written in Uthmani script

## Problem
Text copied from an Uthmani Mushaf («ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ», «وَأَقِيمُوا۟ ٱلصَّلَوٰةَ», «يَٰٓأَيُّهَا») does not fully match today, because the Uthmani rasm differs from the Imlaei (Simple) text in letters and in word boundaries. Stripping diacritics is not enough: «ٱلْعَٰلَمِينَ» → «العلمين», but the Simple text gives «العالمين».

## Requirements
1. Build a second word stream from the Uthmani file with the same positions/ayah structure. Design an Uthmani normalization: the dagger alef (U+0670) and small waw/yeh (U+06E5/U+06E6) stand for letters in Uthmani. Because «الرحمٰن» is written «الرحمن» by users while «العٰلمين» is written «العالمين», index **both** keys per Uthmani word (dagger removed and dagger → ا) and accept either. Measure how many Uthmani words collide with a different Simple word under each key and report it.
2. Align Uthmani words to Simple words **per ayah** (word counts differ: «يَٰٓأَيُّهَا» is one Uthmani word and «يَا أَيُّهَا» is two Simple words). Use DP alignment on normalized forms; store the mapping so `Ref` numbering stays in Simple words. Write a check that runs the alignment over all 6236 ayahs and reports ayahs where the alignment cost is suspicious; list them for me to review rather than silently accepting.
3. Seed from both streams; a match found via the Uthmani stream reports `script="uthmani"` (new field on `QuranMatch`) and returns `reference_uthmani` as the matched Uthmani words, not whole ayahs.
4. The same status gates apply; no gate gets looser.

## Tests (inputs read from the Tanzil files, never typed)
- Uthmani 1:2, 2:153, 2:43 (contains الصلوة), the whole of surah 112 → `verified` with the right refs.
- An Uthmani quote with one word replaced → `altered`, diff shows the Uthmani expected word.
- Negative: ordinary text containing «العلمين» or «الكتب» as normal words → no match.

## Report
Collision counts, suspicious alignments, before/after on the full-corpus tests, latency impact.
