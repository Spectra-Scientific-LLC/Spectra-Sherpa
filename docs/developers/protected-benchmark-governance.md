# Protected Benchmark Governance

SpectraSherpa publishes the governance contract for protected benchmarks
without publishing the protected spectra, labels, sample metadata, storage
locations, or credentials. This keeps validation claims inspectable while
preserving the value of an unseen confirmation set.

The machinery consists of:

- `contracts/protected_benchmark_registry_v1.json`, the closed public registry
  schema;
- `contracts/benchmark_preregistration_v1.json`, the closed protocol schema;
- `benchmarks/protected-registry-v1.json`, the public non-disclosing registry;
  and
- `scripts/verify_protected_benchmarks.py`, the semantic and data-absence
  verifier used by tests and packaging CI.

The closed preregistration schema is the P1 template: it enumerates every
field that must be frozen while rejecting undeclared additions. P2 supplies
the first real instance rather than committing a fictional example that
could be mistaken for protected-set evidence.

The committed registry is intentionally empty at the P1 stage. An empty,
valid registry proves that the governance machinery exists; it does **not**
claim that a protected dataset exists or close the P2 applied-evidence gate.

## Public and protected tracks

`public_reproducibility_only` identifies fixtures whose data and splits are
available to everyone. They support deterministic regression tests and
independent reproduction, but cannot be unseen confirmation evidence.

Protected entries have one of three statuses:

- `provisional_internal`: may support a genuinely blind internal
  architectural study, but public performance claims are prohibited;
- `claim_eligible`: independently reviewed and eligible for a separately
  preregistered public-performance study; or
- `retired`: no further evaluation is permitted.

A public fixture cannot be promoted into a protected entry. Protected status
history must begin with `null → provisional_internal`; the only later
transitions are `provisional_internal → claim_eligible`,
`provisional_internal → retired`, and `claim_eligible → retired`.

Changing only the current status is invalid. Promotion to `claim_eligible`
requires a matching transition plus a separately attested, independent
governance review. The promotion actor, review digest, and review time must
match that review, and the reviewer must differ from the benchmark steward,
data custodian, and study operator.

The M3.5b ledger prevents one organization from resetting a public
benchmark/split attempt history by creating a new campaign. For a protected
study, that local rule is necessary but not sufficient: P2's
custodian-controlled access log must cover every authorized deployment and
organization that can reach the sealed confirmation split. M3.7 admission
must reconcile the local signed receipt chain with that custodian-wide
history before releasing a protected capability.

## What the public registry contains

A protected registry entry contains only:

- an opaque `pbm-…` identifier;
- SHA-256 digests of canonical sealed dataset, label, development-split, and
  confirmation-split artifacts;
- an enumerated provenance class;
- opaque `urn:spectra:…` references for provenance, accountable roles,
  custody, access policy, access log, and protocol;
- a non-use attestation digest;
- allowed and prohibited use codes;
- append-only status-transition evidence; and
- claim-review evidence when applicable.

Opaque references are identifiers, not locators. URLs, filesystem paths,
email addresses, credentials, query tokens, free-form raw diagnostics, and
embedded samples are rejected by the closed schema.

The artifact digests use `sealed-artifact-bytes-v1`: SHA-256 is computed over
the exact immutable bytes held by the custodian. This definition lets CI
detect an accidental copy of those bytes in source control, a wheel, a source
distribution, or another scanned archive.

## What preregistration freezes

The preregistration contract fixes, before confirmation access:

- the objective, intended-use reference, target-population reference, and
  true independent unit;
- protected benchmark identifier and frozen split digests;
- primary metric, direction, minimum meaningful change, and reproducibility
  tolerance;
- uncertainty method and confidence level;
- frozen workflow/evidence baseline;
- transparent-grid search space and execution profile;
- allowed Harness search space, candidate/time/concurrency budgets, and
  stopping rule;
- confirmation release and consume-on-failure rules;
- permitted human interventions and exclusion policy; and
- whether the intended evidence is internal architectural proof or a public
  performance claim.

The governing Harness contract permits at most two infrastructure
replacement authorizations for one confirmation authorization. Accordingly,
`confirmation.max_replacements` accepts only `0`, `1`, or `2`. A larger
number is invalid before confirmation access.

A preregistration marked `public_performance` validates only when its
benchmark resolves to a `claim_eligible` registry entry. A
`provisional_internal` entry may support only internal architectural
evidence.

## Verification

From `packages/spectra-sherpa`:

```bash
python scripts/verify_protected_benchmarks.py \
  --package-root . \
  --scan-root ../.. \
  --artifacts dist
```

The verifier:

1. validates both published Draft-07 schemas;
2. validates registry status history, use restrictions, and claim promotion;
3. optionally validates each preregistration's protocol identifier, exact
   file digest, and split digests against its registry binding; and
4. rejects any scanned file or archive member whose bytes match a protected
   dataset, label, or split digest.

The OSS security preflight and publication workflows run the same check after
building wheel and source distributions.

## P2 registration

P2 adds the first real `provisional_internal` entry only after a scientific
benchmark steward and data custodian can supply the required provenance,
custody, split, non-use, and protocol attestations. The raw artifacts remain
outside the repository.

If no suitable lab-owned set exists, the registry stays empty. Frozen public
and synthetic fixtures may still prove the M3/M4 engineering machinery;
partner acquisition becomes the gate for P2, the protected blind study, and
every external quantitative or comparative Harness claim.
