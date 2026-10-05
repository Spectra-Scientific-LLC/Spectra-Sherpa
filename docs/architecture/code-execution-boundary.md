# Code Execution Boundary

SpectraSherpa OSS is a closed scientific application. It executes operations
from the canonical node registry shipped in the installed SpectraSherpa
release. It does not discover Python files in user directories, load plugin
entry points, install workflow dependencies, execute downloaded packages, or
interpret a workflow field as Python, shell, pickle, a callable path, a
container specification, or another executable instruction.

This is intentionally stricter than a general scientific programming
environment. Scientists can inspect and modify the open source, contribute a
new canonical node through review, or run exported code themselves in an
environment they control. The installed Workbench does not silently turn those
possibilities into ambient code-execution authority.

## What local OSS executes

- the installed SpectraSherpa application;
- the exact built-in node implementation named by an admitted canonical DAG;
- bounded subprocess workers started by the canonical executor; and
- configured optional scientific libraries, such as SpectroChemPy, only when a
shipped node explicitly declares that dependency.

The node registry is populated from shipped modules and then frozen. It cannot
be expanded, replaced, or reduced at runtime. A workflow can select and
configure an installed operation; it cannot register an operation.

Optional packages are installed by the scientist or administrator before the
application starts. A workflow cannot ask SpectraSherpa to install one.

Generated Python and notebooks are download artifacts. SpectraSherpa never
executes them automatically.

## Data acquisition is not code acquisition

HITRAN, NIST, and Eigenvector Research resources are scientific data. Their
acquisition requires an explicit scientist action or an explicit deployment
setting, uses a source-specific HTTPS boundary, and produces data for a
shipped parser. Downloaded bytes never become an import path, package,
executable, plugin, or shell command. The optional SpectroChemPy boundary does
not discover or download data; it is invoked only when a scientist executes
EFA, MCR-ALS, or SIMPLISMA.

## Hybrid jobs

Hybrid does not broaden this into remote code execution. The scientist starts
and consents to one disclosed job. The device then admits a declarative,
version-pinned canonical DAG against the locally installed registry and the
device's local node and capability allowlists. Only the intersection is
eligible to run. The job executes under the governed worker's process,
resource, timeout, cancellation, and evidence controls.

Consent authorizes that bounded job; it does not authorize new code. Hybrid
must reject Python, shell, wheels, source archives, pickles, callable paths,
plugin identifiers, dependency-install instructions, containers, or any node
that is absent from the local allowlist. The preview shown before consent must
name the DAG, data binding, local nodes, resource envelope, and permitted
egress. Cancellation and the local kill switch remain authoritative.

## Release boundary

The public package is materialized from the reviewed monorepo subtree. Release
automation inspects public-repository content as data and never invokes its
scripts. Before any write credential is created, the trusted monorepo verifier
checks the complete candidate tree, Git object modes, dependency sources and
hashes, reviewed bundle and diff digests, public-branch ancestry, and exact
tree fidelity. Built wheels must be universal pure-Python archives; package
checks reject links, traversal entries, special archive members, and native
executable payloads.

These controls prevent SpectraSherpa's extension or publication mechanisms
from introducing arbitrary executable content. They do not claim that any
software distribution ecosystem can make an absolute guarantee about every
upstream dependency. Release qualification therefore also audits the locked
dependency set and publishes only the reviewed, versioned artifacts.
