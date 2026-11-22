# AI review of settlement pairs

**Publish dashboard** sends unresolved pairs to Gemini 4 Hydrogen after
discovery. Gemini accepts both official PDFs and the inline market rules in one
request. Google lists standard input and output as free within each project's
quota. Groq's free GPT-OSS 120B tier advertises fixed quotas and structured text
output. Gemini can also read the layout of the source PDFs.
[Gemini pricing](https://aistudio.google.com/docs/pricing#gemini-4-hydrogen) ·
[Gemini document processing](https://aistudio.google.com/docs/document-processing)
· [Groq limits](https://console.groq.com/docs/rate-limits)

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

`review.json` records each manual-review pair, its source PDFs and hashes, and
the status of the AI review. Reviews can suggest likely equivalence,
cancellation-only differences, other settlement differences, or insufficient
evidence. Each substantive suggestion needs quotes from both venues. Likely
equivalence and cancellation-only suggestions need citations from both governing
PDFs. Quote text is checked against the specified PDF page or the inline rules,
with page 0 indicating inline rules. Scanned pages can require human verification
when text extraction cannot support a quote.

A human still needs to check the full terms and approve equivalent pairs through
[`data/reviewed_pairs.json`](../data/reviewed_pairs.json). The dashboard builds
from the deterministic settlement report while AI review runs in parallel.

## Quotas and cache

The job makes up to 30 new requests per run and stops on a quota response.
Unreviewed pairs carry forward when rediscovered. The GitHub Actions cache reuses
validated responses by model, prompt, exact market terms, and document hashes.
Pairs with no previous attempt receive priority over failed attempts. Missing
credentials and provider errors appear in the artifact. Google's actual free
quota is project-specific, so the number of new pairs reviewed per day can vary.
[Gemini API rate limits](https://aistudio.google.com/docs/rate-limits)

The request sends public venue rules only and disables interaction storage.
Google's unpaid-service data terms still apply.
[Interaction retention](https://aistudio.google.com/docs/interactions-overview#data-storage-retention)
· [Gemini API terms](https://aistudio.google.com/docs/terms#unpaid-services)
