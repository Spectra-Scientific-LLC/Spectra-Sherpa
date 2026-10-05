# Native desktop security qualification

This slice extends the #1129 internal native candidate boundary checks. It does
not authorize public distribution or claim signing/clean-machine acceptance.

## Ownership correction

An abrupt backend exit previously bypassed normal worker-pool cleanup. A running
scientific subprocess could continue computing after its owner disappeared.
Each isolated worker now waits on its actual spawning process's OS sentinel
and exits itself when that owner exits. This uses no process-name/port scan and
never signals an unrelated PID. Graceful pool cleanup remains unchanged.

A real spawned-process test starts a long computation, abruptly exits its parent,
and verifies inherited output handles close before the computation's sleep can
finish. It exercises the Windows-compatible multiprocessing sentinel mechanism;
the Windows runner still supplies the actual platform receipt.

## Boundary tests

- Ten Node tests cover child transport, startup refusal/cleanup, endpoint and
  window identity, cross-origin credential stripping, navigation, redirects,
  webview refusal and popup refusal.
- The native smoke harness adds a real second loopback service as a hostile
  destination. A renderer request is refused and that server receives zero
  requests. This passed against the actual packaged Apple Silicon candidate.
- Twenty-three executor-pool tests passed, including the abrupt-parent case.

## Remaining production controls

Release packaging must apply/verify Electron fuses before signing, retaining
only the bundled application and disabling unused Node launch/debug entry
points. Signed nested-code and installer acceptance are separate receipts.
File/export dialogs, background watching and user-confirmed shutdown belong to
the scientist-lifecycle slice. No update service or renderer IPC privilege was
introduced here.
