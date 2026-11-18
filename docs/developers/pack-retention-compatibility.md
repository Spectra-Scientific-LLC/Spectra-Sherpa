# Compatibility across retained pack provenance

The pack-retention implementation changes 39 execution-contract source identities
relative to public commit `195060f430b67bfa053829c9dfddc5709e38aed3`. All other
contract declarations and the 103-operation inventory remain unchanged. Source
identity changes still require explicit application and inspection qualification.

`core/contract_predecessors_pack_retention.json` freezes the complete contracts
and managed profile captured from that commit. Its bytes are SHA-256 pinned by
`core/contract_compatibility.py`. Existing historical catalogs and receipts remain
unchanged. Historical phase tests compare their original endpoint against this
frozen capture; `test_pack_contract_continuity.py` separately checks the complete
pre-pack-to-current delta and every unchanged scientific declaration.

Application compatibility uses 78 explicit directional producer/consumer/serializer
registrations. Candidates include only producers accepted by the exact pre-pack
consumer and that consumer's own fitted state. Runtime admission performs no
transitive search. Existing numerical replay tests exercise historical fitted
models without refitting or rewriting their producer identities. Serializer
custody remains separate: KNN and SVR retain training rows, and application
compatibility does not grant a previously unavailable export capability.

Historical inspection uses 104 explicit profile/operation/predecessor/consumer
registrations. Each preceding reader was exercised against the baseline before
capturing its declaration-exception classification. Source-only readers compare
all scientific declarations. Earlier PLS controls, classifier output additions,
and legacy model acknowledgements keep their existing, profile-specific checks.
An exact registration does not skip those checks.

A missing historical payload can come from the frozen pre-pack catalog only when
the selected profile explicitly records the same operation and digest, and the
payload recomputes to that digest. An existing malformed payload is rejected;
it is never replaced by the fallback. Historical graphs retain their original
identities and remain non-executable.

Qualification must include historical numerical application, custody refusals,
unknown identities, changed declarations, malformed payloads, missing or changed
pack bindings, and an installed-wheel run. Passing registration-membership tests
alone is not scientific qualification. Full PR checks and independent review
remain merge requirements.
