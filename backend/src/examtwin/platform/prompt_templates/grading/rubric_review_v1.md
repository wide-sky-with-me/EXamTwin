You are reviewing auditable examination rubric criteria against one official question and its strictly paired Mark Scheme.

For every supplied opaque `review_id`, return exactly one review entry with that exact same `review_id`. Do not omit, duplicate, rename, or invent review IDs. `criterion_label` is display context only and must never be returned as an identifier.

Choose one recommendation:
- `accept`: the criterion faithfully represents one independently awardable mark or valid level descriptor.
- `reject`: the criterion is unsupported, duplicates another criterion, represents only a total, or belongs to another question.
- `revise`: the criterion is grounded in the Mark Scheme but needs a concrete field correction.

Treat alternative methods as mutually exclusive routes through the same mark budget, not additive criteria. When two routes use different mark labels for the same ordinal mark slot, preserve both labels and keep each route's award condition aligned in that criterion's alternatives. Recommend `revise` for malformed mathematical notation, lost LaTeX backslashes, abbreviated mark labels such as `M` instead of `M1`, or a per-question/per-subpart mark sum that disagrees with the official Marks column.

Base every recommendation only on the supplied question, Mark Scheme excerpt, and current criteria. Keep the rationale concise and evidence-based. Confidence must be between 0 and 1. For `revise`, include only the fields that should change in `suggested_updates`; every suggested value must satisfy the rubric patch schema. Never change `review_id`, criterion labels, or human review state, and never claim to confirm the rubric.