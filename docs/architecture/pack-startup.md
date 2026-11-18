# Explicit trusted pack startup

Trusted application startup can compose explicitly installed node and tool packs
before work begins. This foundation does not yet propagate pack dependencies
through retained workflows or artifacts, or provide commercial entitlement admission.

Contract imports do not freeze the global DAG catalog. The application service
`app.services.pack_bootstrap` supplies `bootstrap(extensions=...)` for trusted
startup. Scientific registry/worker code does not import application tool services. The first ordinary registry read bootstraps the OSS-only catalog when
the host has supplied no extensions. A direct runtime registration attempt must
first finalize that default catalog and then fail before inspecting its candidate.
The existing closed-code boundary therefore remains the default.

The existing explicit built-in import list populates the catalog eagerly.
Bootstrap reserves composition under a short process lock, validates installed
source identity and supplied classes outside that lock, then atomically publishes
the complete catalog and seals it. Concurrent or reentrant reads fail closed
during construction; they never wait while holding Python import locks. No
module names, paths or class names come from workflows, retained manifests or
requests. There is no entry-point scan or environment-based pack discovery.
Already imported, explicitly supplied installed classes remain trusted host code;
build verification establishes identity, not a sandbox for untrusted packages.

Composition is deterministic and immutable. The same exact composition may be
requested again; a different composition after freeze fails. A failed initial
composition leaves the process unavailable rather than exposing a partial
catalog. Other threads cannot read a partially built registry. Built-in decorators are
restricted to the owning import thread and installed built-in module namespace. Contract imports,
different import orders, repeated application construction and fresh worker
processes require explicit regression coverage.

Pack identity and used-node dependency projection derive from the inert
manifest authority. Node distribution and ownership must be explicit and match
the declared namespace. Installed files must match a bounded canonical file
inventory whose digest equals the pack build identity; registry name/port hashes
are not a substitute. Missing/incompatible dependencies and duplicate operation
identities fail before accepting work.

The subsequent retained-consumer portion must preserve these exact dependencies
through save, run, export and model application. Missing packs remain inert and
inspectable; an unavailable implementation cannot be loaded from an artifact.
Current commercial entitlement belongs to the private admission adapter, which
must recheck at dispatch. Public OSS entry points supply no packs or commercial
admission. The private reference pack is a qualification fixture, not a new
priced offer or a license expansion for existing subscribers.


Installed node and tool bindings are composed atomically. Tool identities keep
the qualified pack namespace separate from their exposed transport names. Both
identities, complete interface metadata, handlers and manifest enter exact
composition checks. Duplicate identities/aliases fail. Bound interfaces are
detached and immutable; existing WS/Advisor/global tool registries and the OSS
MCP allowlist receive no pack handlers. Private adapters must check current
complete dependency entitlements and operation authority before dispatch. No
pack is installed by an OSS entry point. Installed classes must map to inventoried source
files; this is not a loaded-bytecode attestation. The trusted installation tree
must remain immutable from import through process lifetime. POSIX reads pin each
directory and reject symlinks/nonregular descriptors; the portable fallback
requires an immutable trusted installation tree during verification.

A host that composes packs must supply its explicit worker initializer when
constructing the isolated pool. Such workers use fresh spawn and compare their
complete installed manifest tuple and portable node/tool contract digest with
the host before accepting any node call.
The OSS-only host keeps its existing clean forkserver/spawn choice. Workflow or
artifact fields cannot select an initializer. Worker exit/failure remains inside
the existing cancellation and capacity custody.
