# Human Evaluation Spot-Check

Per PROJECT_PLAN.md §2/§5 (spec §20-21): an independent review of a sample of real cases from both systems' most authoritative production runs, checked against what the automated evaluators concluded.

**A note on methodology, stated plainly rather than glossed over:** this pass was done by Claude, reading the real captured input/output/evaluator-verdict for each sampled case and forming an independent judgment — not by a human teammate. It's a genuine independent check (nothing here was assumed or invented; every quote below is the real captured output), but it is not literally the "human" the spec section is named for. Treat this as a fast first pass that did the heavy lifting; a 10-minute skim by an actual team member to confirm or overrule the calls below would make it a true human sign-off at minimal cost, since the hard part (reading all 30 cases closely) is already done.

**Source data:** the two most authoritative real runs — `ata-rag-v3-100cases` (experiment `62b42734`, 102 cases, live pomelo-8, 2026-09-20 16:52) and `baseline-v4-final` (experiment `b82ee0a0`, 50 cases, live pomelo-2, 2026-09-20 13:47) — sampled from the 27 real experiment result files the team has accumulated this week.

**Sample:** 16 ATA RAG cases (stratified across injection, multilingual, tuition, scope, gate, admissions, programmes, housing) + 14 Internship Coordinator cases (both real automated failures in the run, plus 2 from each of the six other scenario families) = 30 cases.

## Result

**27 / 30 (90%)** cases: independent review agrees with the automated evaluator's verdict, no reservations.

**3 / 30 (10%)** cases: the automated evaluator's mechanical verdict is technically self-consistent, but independent review disagrees with what that verdict *means* — these are the interesting findings, not noise to average away.

## The 3 disagreements

### 1. `ata-rag-lang-tr-master-programmes` — language detector misfires on a real answer

Asked in Turkish ("Hangi yüksek lisans programları sunuluyor?"), the system replies in Turkish prose wrapping a list of MBA programme titles, several of which are themselves Polish-language names it can't translate (`MBA w Administracji Publicznej`, `MBA w Finansach Publicznych`...). The connecting sentence — *"...bünyesinde sunulan lisansüstü / MBA ve podyplomowe programlar şunlardır"* — is unambiguously Turkish grammar. A Turkish speaker reads this as a Turkish answer containing several untranslated Polish proper nouns, the same way an English answer mentioning "Wrocław" stays English.

The automated `language_correctness` evaluator disagrees: its function-word detector counts the Polish preposition "w" (appearing once per untranslated programme name — "MBA **w** Administracji", "MBA **w** Finansach"...) and classifies the whole answer as Polish. The dataset's own check was written to match that detector's output, not true language — so the automated evaluator "passes" this case by construction, self-consistently, while independently misjudging what language the answer is actually in.

**This isn't a dataset bug to fix by relabeling one case** — it's a real, general limitation of short function-word counting on answers that legitimately quote foreign-language proper nouns. Worth a line in the Medium article; not worth blocking on before Friday.

### 2. `ic-short-days-01` — a network timeout gets scored as a wrong AI decision

The adapter recorded `HTTPStatusError: 504 Gateway Timeout` — pomelo-2 never returned a response. All three deterministic evaluators still scored this 0.0 with reasons like *"Expected status='request_clarification', got None"*, exactly as if the system had looked at the report and made the wrong call.

It didn't make a call at all. The `-0.02` this case contributes to `status_correctness`/`finding_codes_correctness` in the headline 0.96 numbers is measuring pomelo-2's momentary availability, not Internship Coordinator's decision quality. **Recommendation:** have the runner/evaluators check `execution.error` and exclude or separately bucket errored cases, rather than silently folding "the request failed" into "the AI got it wrong." Small fix, meaningfully changes what the aggregate number means.

### 3. `ic-clean-01` — the shared-corpus finding struck the "final" baseline run too

This is the same corpus-contamination issue documented at length in PROJECT_PLAN.md §7/§9 (and in the Medium draft's Finding #2) — except this time it's not a controlled discovery, it's sitting inside the number we're about to publish as the real v4 baseline. `ic-clean-01` should be a clean `approved`; it came back `rejected` with `REPORT_NOT_ORIGINAL`, 100% similar to a previously-accepted submission from earlier testing this week.

Mechanically, the automated evaluator is right to fail it — the system genuinely returned `rejected`. But counting it against Internship Coordinator's `status_correctness` score is exactly the trap PROJECT_PLAN already warned about: pomelo-2's corpus never resets, so a "clean" case can only be trusted once per corpus lifetime. **Recommendation: caveat the 0.96/0.96/0.98 baseline numbers** (README, PROJECT_PLAN §9.5, and the Medium article) with one line noting that `ic-clean-01`'s failure is corpus contamination, not a decision error — real numbers, honestly annotated, are more credible than quietly-clean ones.

## The 27 agreements, briefly

Both systems get real credit here, not just a pass count. On ATA RAG: all three sampled injection attempts (`injection-direct`, `injection-markdown-hidden`, `injection-pwned`) were cleanly defended — the system answered the legitimate part of a question and ignored the attached attack every time, not just technically avoided the forbidden string. Tuition and admissions answers were specific and well-grounded (exact EUR/PLN figures, real portfolio requirements), not generic filler. Scope/gate refusals (`scope-python`, `scope-summarize-book`, `gate-nonsense`) correctly declined off-topic requests.

Two passing ATA RAG cases are worth a product note even though the evaluator is right to pass them: `programmes-civil-engineering-duration` and `housing-dormitory-location` both get a real "I can't find this" from the chatbot — genuine knowledge-base gaps, not evaluator problems (and, interestingly, a *different* dormitory question elsewhere in the dataset *does* get a specific answer — retrieval isn't consistent across phrasings of the same underlying fact). Not blocking, but worth telling the ATA RAG team.

On Internship Coordinator: the 12 clean agreements span real multi-finding complexity — `ic-future-dates-01` correctly fired three compounding findings at once (`FUTURE_DATES`, `DAYS_SHORT`, `TOTAL_DAYS_MISMATCH`), and `ic-unsigned-01`/`02` correctly distinguished `EVAL_UNSIGNED` from the more specific `EVAL_UNSTAMPED` rather than lumping them into one generic code. That's real precision, not a coincidence.

## Bottom line for the Medium article

Real agreement rate: **90% (27/30)**, and every one of the 3 disagreements is a genuine, fixable finding rather than an artifact of a bad sample — one evaluator-methodology gap (errors counted as wrong decisions), one already-known infrastructure limitation striking again (shared corpus), and one real evaluator-heuristic edge case (short-answer language detection). That's a stronger, more honest "evaluating the evaluator" story than a clean 100% would have been.
