# Free AI API for settlement review

Reviewed November 19, 2026 against provider documentation. The recommendation
assumes a low-volume, internal trial on public venue rules or synthetic fixtures.
SignalScout accuracy, turnaround time, and account-specific quotas remain unmeasured.

## Recommendation

Start with Google Gemini Developer API **Gemini 4 Hydrogen** (`gemini-4-hydrogen`)
for advisory triage of SignalScout’s `manual_review` candidates. It accepts a PDF
and the market terms directly and supports JSON Schema output in the same request.
Standard input and output are free within the project’s quota. Google released
the stable model on November 12, 2026 and lists no shutdown date.
[Model capabilities](https://aistudio.google.com/docs/models/gemini-4-hydrogen)
· [Structured output](https://aistudio.google.com/docs/structured-output)
· [Pricing](https://aistudio.google.com/docs/pricing#gemini-4-hydrogen)
· [Release and shutdown dates](https://aistudio.google.com/docs/deprecations#gemini-4-models)

- **Capacity.** Check the active requests-per-minute, input-tokens-per-minute,
  and requests-per-day limits for the specific project in AI Studio. Quotas are
  shared across the project’s keys and the daily quota resets at midnight
  Pacific time. Keep the trial on a free-tier project without billing enabled
  and cap submissions so a quota error leaves cases in the review queue.
  [Rate limits](https://aistudio.google.com/docs/rate-limits)
  · [Billing](https://aistudio.google.com/docs/billing)
- **Documents.** Use inline `application/pdf` for the small rulebooks SignalScout
  already fetches. Google documents a ceiling of 50 MB and 1,000 pages per PDF,
  subject to the model’s 1,048,576-token context window and the project’s quota.
  Google recommends the Files API for larger PDFs that will be reused. Uploaded
  files expire after 48 hours and can be deleted sooner.
  [Document processing](https://aistudio.google.com/docs/document-processing#limits-and-scaling)
  · [Model limits](https://aistudio.google.com/docs/models/gemini-4-hydrogen)
  · [File deletion](https://aistudio.google.com/docs/files#delete-uploaded)
- **Data use.** Under the standard unpaid terms, Google can use inputs and
  outputs to improve its products and human reviewers may see them. Use only
  public venue evidence and synthetic fixtures. Set `store: false` for a
  synchronous Interactions API call to disable interaction storage. The unpaid
  data-use terms still apply. Google has separate terms for the EEA, Switzerland,
  and the United Kingdom, including a paid-services requirement for making API
  clients available to users in those regions.
  [Gemini API terms](https://aistudio.google.com/docs/terms)
  · [Interaction storage](https://aistudio.google.com/docs/interactions-overview#data-storage-retention)

## Free alternative

GroqCloud lists `openai/gpt-oss-120b` as a production model with strict JSON
Schema output. Groq’s published free-plan limits for it are 30 requests per
minute, 1,000 per day, 8,000 tokens per minute, and 200,000 tokens per day.
Check the organization’s limits page for its actual quotas. The model accepts
text, so SignalScout would need to extract rulebook text locally and OCR scans,
keeping page numbers and checking that tables survive extraction. Groq may
retain inference data for up to 30 days for reliability and abuse monitoring.
Organization admins can enable zero data retention for inference. Try Groq if
Google’s unpaid data terms are unsuitable and local extraction covers the corpus.
[Model catalog](https://console.groq.com/docs/models#production-models)
· [Model inputs](https://console.groq.com/docs/model/openai/gpt-oss-120b)
· [Structured outputs](https://console.groq.com/docs/structured-outputs)
· [Rate limits](https://console.groq.com/docs/rate-limits)
· [Data controls](https://console.groq.com/docs/your-data)

## Pilot with SignalScout’s review queue

1. Use `manual_review` rows from `settlement-review/assessment.json`. Send the
   row’s reason, both venues’ public settlement terms, and the available official
   rulebook PDFs from SignalScout’s evidence-fetching step. Record the exact
   source URLs and document digests with the result. Treat all venue text and PDF
   content as evidence, and make the request without search or executable tools.
   [Assessment workflow](../README.md#market-dashboard)
2. Ask for a suggested review priority, differences or ambiguities by clause,
   missing evidence, and short supporting quotes with their venue and page or
   section. Allow the model to report insufficient evidence. Validate the schema
   and verify quoted text against the originals before presenting a finding as
   supported. Correct JSON can contain invented quotes or miss a dispositive
   exception. Keep each candidate in `manual_review` until a reviewer confirms it
   through the existing approval workflow. Quota, timeout, and validation errors
   leave the candidate available for ordinary review.
   [Google’s structured-output limitations](https://aistudio.google.com/docs/structured-output#limitations)
   · [Manual approval workflow](../README.md#market-dashboard)
3. Compare the suggested findings with a human-labeled set of equivalent pairs,
   cancellation-only differences, other settlement differences, and incomplete
   evidence. Include scanned pages, date cutoffs, and potential conflicts between
   market-specific clauses and general rulebooks. Measure missed material
   differences, quote accuracy, abstentions, failed calls, and reviewer time to
   decide whether the trial helps.
