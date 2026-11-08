# How I used AI tools

I used AI tools throughout this project. I chose the problem, set the scope and made the design decisions; the AI helped me write and check the work. I verified results by running tests, benchmarks and real-browser click-throughs, not by trusting what a tool said.

## Tools
- **Claude (chat):** compared the five problem statements and helped me pick this one. Helped me write the spec ([SPEC.md](SPEC.md)): scope, data model, matching rules and assumptions.
- **Claude Code:** implemented the code milestone by milestone from my spec, wrote tests, and ran checks and browser click-throughs. Its commits carry a `Co-Authored-By` trailer.
- **Gemini API (Google AI Studio):** the in-product AI feature that suggests column mappings, plus `scripts/eval_ai_mapping.py` to measure its accuracy.
- _[ChatGPT / other tools I used personally: what I used each for]_

## What I checked and decided myself
- **The AI feature was tested with a real key, not only mocks.** The first real run showed every suggestion silently falling back to fuzzy matching: `gemini-2.5-flash` returns 404 to new API keys. The fallback worked as designed, but the AI was never used. I made the model configurable and switched to `gemini-3.1-flash-lite`, after comparing models on all 20 layouts (194/194 fields right, about 2.6 s per file).
- **The AI swapped TCS and TDS** on a deliberately cryptic layout (`Tax A` / `Tax B`), at a confidence of 0.70. That was just above the review threshold, and both columns held valid amounts, so nothing flagged it. I added rule-based plausibility checks on the 20 preview rows (TCS should be larger than TDS; gross minus deductions should equal net). A swap is now flagged and cannot be approved without confirming. I also corrected the prompt.
- **Proxy cookie mode for Safari and phones.** The frontend and backend live on different domains, so a direct API call makes the session cookie third-party, and Safari and iPhones drop it. I chose to forward `/api` through Vercel so the cookie is first-party. I accepted the trade-off of a ~4.5 MB upload limit through the proxy and documented it.
- **No database foreign keys on the high-volume tables** (orders, partner lines, recon results). Postgres checks them row by row: 31 s for 1 lakh orders with them, 18 s without. Integrity is still kept: only the ingest pipeline and the engine write those tables, every id they use comes from a record they have just validated, and the low-volume tables keep their foreign keys.
- **Matching and expected amounts are rules, not AI.** Money decisions have to be exact and explainable, so the engines are pure, tested functions. The AI only proposes column mappings, which a person previews on 20 rows and approves before they are saved, with versions for rollback.
