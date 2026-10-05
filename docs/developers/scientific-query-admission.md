# Scientific query scope and active attention

## One useful call per ordinary turn

The first answer/proposal call also checks broad relevance. There is no preliminary
classifier, classifier JSON, short classifier token cap, or second filter receipt.
Reject obvious unrelated use or abuse; allow scientific analysis, methods,
statistics, analysis programming, platform help, troubleshooting, greetings and
follow-ups. Ambiguity calls for help or clarification, not a narrow task taxonomy.

A refusal is exactly:

> Spectra Sherpa is a scientific data analysis platform. Adjust your query.

The shared policy is prepended to the existing task prompt. It sees only the
context already authorized for that task. This is behavioral scope control,
not an access or privacy boundary: entitlement, session, project ownership,
disclosure, proposal validation and execution safeguards remain mandatory.

| Surface | Single-call implementation |
| --- | --- |
| OSS pip/macOS/Windows | Configured BYOK provider receives scope and attention in its ordinary chat request. Missing BYOK remains a setup error. |
| Hosted chat / code / stories | Engine and commercial provider boundary include the same scope policy; ordinary response budgets are unchanged. |
| Tool chat, including signed Hybrid | Inspect text before tool dispatch. A refusal wins over mixed text/tool output; no draft or tool is created. |
| Managed optimization | Native output schema has `decision: scientific_query_rejected` with `proposal: null`. It is terminal after one attempt and replays without another call. Existing proposal identities retain their historical schema. |

Streaming buffers only a possible leading refusal, independent of chunk
boundaries. Normal answers stream once their prefix differs. Providers are drained
for usage accounting even after a refusal; trailing refusal output is suppressed.
Quoted refusal text later in an answer remains ordinary text. Separate provider
reasoning blocks are not interpreted as visible answers.

Refusals consume the ordinary model usage and one Demo turn. HTTP admission
checks input bounds and consent without model egress; a Demo reservation starts before streaming headers and lasts
through its response stream. Requests rejected before provider egress release
the reservation without charging. Existing WebSocket reservations and Pro metering
remain authoritative. The ordinary retained response handles replay; no extra
classifier cache exists. Tool-dependent rounds and bounded invalid-proposal
retries remain separate calls where their results are needed.

## Guidance and attention

After two rejected turns, the client supplies deterministic, attention-specific
suggestions. “Ask Sherpa” fills the input without sending. Suggestions continue
on further refusals and clear on a successful answer or sign-out. This requires
no extra LLM call. Follow-up suggestions already accompany ordinary answers.
Ambient idle Guidance retains its existing separate fallback.

`active_attention` contains a bounded window/surface and optional opaque node,
plot and renderer identifiers. Focus updates on pointer/keyboard interaction and
clears on navigation/unmount. It contains no sample values, labels or DOM text.
Hosted disclosure treats attention as metadata; saved graph/run authority still
establishes scientific identity and population. Hybrid sends only coarse
window/surface, never local node/plot identities. Attention cannot authorize a
tool, reveal data, or substitute for absent scientific evidence.

## Verification and deployment qualification

Run shared scientific-query, server single-call/admission, managed-workflow wire,
production Advisor, Hybrid, context and frontend Guidance/chat suites. Provider
substitutes prove call counts, refusal framing, pre-tool refusal, usage, quota
and replay; they do not prove a real model's relevance accuracy or latency.

During qualification, try a scientific question, loosely related platform help,
a short follow-up, two obviously unrelated requests, then a scientific question.
Check the exact refusal, repeated Guidance, its reset, and plot-specific focus.
Repeat with each configured BYOK/managed model. Verify one model call for each
ordinary answer/refusal, one billed turn, and no extra call on a retained replay.
Check a refused campaign creates no candidate/draft and does not retry. Test
BYOK unavailability and revoked disclosure/session access.

Measure end-to-end latency separately: removing a classifier eliminates one
sequential round trip, but does not establish a measured percentage speedup.

## Deployment note

Server migration `0113_scientific_query_refusal` adds a nullable refusal code to
the managed proposal record; existing records remain unchanged. The exact
provider-byte digest stays in `output_digest`. Replaying a refused request reads
the retained code and makes no provider call. Downgrade refuses to discard
retained refusal records. The policy digest binds the scope policy and effective
prompt alongside the existing structural task prompt identity.
