# AI review of settlement pairs

**Publish dashboard** sends unresolved pairs to Gemini 4 Hydrogen after
discovery. When Hydrogen cannot produce a usable review, the workflow tries
Gemini 3.6 Flash. Both models accept the governing PDFs and inline market rules.
Google lists standard input and output as free within each project's quota.
[Gemini pricing](https://aistudio.google.com/docs/pricing#gemini-4-hydrogen) ·
[Gemini document processing](https://aistudio.google.com/docs/document-processing)

## Enable the scheduled review

1. Create a key in a Free Tier project in [Google AI Studio](https://aistudio.google.com/api-keys).
   Keep billing disabled to enforce free-only usage. Check the active limits in
   [AI Studio](https://aistudio.google.com/rate-limit).
2. Add a repository Actions secret named `GEMINI_API_KEY` under
   [Settings → Secrets and variables → Actions](https://github.com/alexsaccone/signalScout/settings/secrets/actions).
3. Wait for the next scheduled run or select **Run workflow** on
   [Publish dashboard](https://github.com/alexsaccone/signalScout/actions/workflows/dashboard.yml).
   Download the **settlement-ai-review** artifact from the run summary.

## Read the results

`review.json` records each manual-review pair, its source PDFs and hashes,
review status, and the model behind the selected verdict. Reviews can suggest likely equivalence,
cancellation-only differences, other settlement differences, or insufficient
evidence. Each substantive suggestion needs quotes from both venues. Likely
equivalence and cancellation-only suggestions need citations from both governing
PDFs. Quote text is checked against the specified PDF page or the inline rules,
with page 0 indicating inline rules. Scanned pages can require human verification
when text extraction cannot support a quote.

The Markets page shows the model, suggestion and checked quotes under **AI-reviewed**.
If the AI job fails, the dashboard can still publish from the deterministic
settlement report. A human still needs to check the full terms and approve
equivalent pairs through [`data/reviewed_pairs.json`](../data/reviewed_pairs.json).

## Quotas and cache

The job makes up to 30 total requests per run. Each model backs off after
temporary failures and can resume within the review time budget. An exhausted
quota stops calls to that model for the run. Pairs with no previous attempt receive priority over
failed attempts. Once every pair in the current manual-review queue has an AI
result, remaining capacity goes to Hydrogen rechecks of earlier Flash reviews.
A successful Hydrogen recheck becomes the selected verdict. Both models'
validated results stay in the cache under separate fingerprints.

Cached results can be reused while the prompt, market terms and document hashes
match. Unreviewed pairs carry forward when rediscovered. The artifact and run
summary report actual request outcomes by model separately from pair statuses.
Google's free quota is project-specific,
so the number of new pairs reviewed per day can vary.
[Gemini API rate limits](https://aistudio.google.com/docs/rate-limits)

The request sends public venue rules only and disables interaction storage.
Google's unpaid-service data terms still apply.
[Interaction retention](https://aistudio.google.com/docs/interactions-overview#data-storage-retention)
· [Gemini API terms](https://aistudio.google.com/docs/terms#unpaid-services)
