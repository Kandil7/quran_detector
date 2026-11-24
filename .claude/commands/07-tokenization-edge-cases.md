# Task: tokenization edge cases

Handle and test each of these, measuring the effect on the eval set (no regressions in `verified` precision):
1. Detached conjunction «و الله», «و إن»: join a standalone و / ف with the next word when the joined form exists in the vocabulary and the split form does not continue a match.
2. Merged words «ياأيها», «يااأيها» (OCR/LLM): try splitting unknown tokens into two known words when that extends a match.
3. «لله» vs «ل الله», and «إن شاء الله» written «انشاء الله».
4. Markdown from LLM output (`**`, `>`, `-` lists, `«»` inside bold) must not break spans; add tests with real LLM-style markdown.
5. Arabic presentation forms from PDFs, ZWNJ inside words, mixed Arabic/Persian letters.
Each rule must be individually switchable in `Config` and covered by positive and negative tests.
