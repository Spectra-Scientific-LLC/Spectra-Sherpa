# Pack identity and inert inspection

`core.pack_manifest` defines bounded, immutable metadata for an explicitly
installed pack. It records pack ID/version/build digest, a closed core-version
interval, execution-contract versions, entitlement and license identifiers,
declared node/tool names and exact dependency references. Proprietary operation
names belong to `pro.<pack-id>.<name>`; duplicate identities, incompatible
versions/builds, missing dependencies and cycles are refused.

This metadata is inert. Parsing, validating or comparing it never imports code,
checks out a license, verifies installed bytes or authorizes an operation. A
matching identity is not execution permission. Trusted application composition
must separately verify the installed build, register only explicitly supplied
code and enforce current admission before scientific work. No discovery,
entry-point scanning, workflow-selected modules or renderer code is accepted.

The artifact dependency projection includes only packs owning used nodes and
their transitive dependencies. An unrelated installed pack does not make an
OSS-only workflow require it. Changing build bytes must change build identity,
even when node names and ports stay the same. Catalog fingerprints cannot
substitute for that build identity.

Retained evidence can compare required and installed references and report
missing packs, different versions or different builds without executing them.
This foundation does not yet wire pack metadata into workflow persistence,
artifact exports, the GUI or execution admission. Those consumers must derive
from this authority when introduced. Existing closed-code execution and the
read-only OSS MCP are unchanged.
