# Picomatch audit disposition — November 17, 2026

GHSA-fc5q-39xc-vjpf affects Picomatch through 4.0.7. Attacker-controlled
single-branch repeated extglob patterns can cause exponential regular-expression
backtracking in Node.js. The installed versions remain vulnerable. npm's latest
release is 4.0.7 and the advisory lists no patched release as of this review.
The linked upstream candidate is incomplete; it is not substituted for a release.

This short-lived deployment-specific disposition covers only the frontend lock's
exact 4.0.4 and 4.0.7 development dependencies. Inspected consumers are Vite,
Vitest, Tinyglobby, Vue language tooling and the build visualizer. Patterns come
from repository-owned build/test configuration and source imports. Application
source does not import these matchers. Deployed applications serve compiled
assets; frontend Node tooling and node_modules are not shipped or executed.

The disposition does not cover exposed development servers or untrusted build
configuration. It does not assert that Picomatch itself is safe. Public development
servers retain their localhost default. Production runtime promotion requires
new review and fails the audit automatically.

The full development-inclusive audit remains enabled. The exception binds the
advisory, package, exact lock, high severity and exact versions, expires on
December 1, 2026, and checks every installed occurrence for `dev: true`.
Unknown versions, runtime copies, expired policy and other advisories fail.
Private products must supply their own exact policy; a public exception cannot
waive a sibling product's lock. Recheck for a complete upstream fix before expiry.

Validation includes simulated runtime promotion and unreported duplicate copies,
invalid policy, expiry, scanner errors and advisory/lock/version isolation.
Live full-lock audits are required separately; no package build or historical
scientific qualification is renewed by this policy disposition.
