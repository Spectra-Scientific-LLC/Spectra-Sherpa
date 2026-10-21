# OSS workspace presentation contract

!!! abstract "Summary"
    For contributors: the presentation contract for the local workspace
    interface. It is not a roadmap or a release guarantee; installed behavior is
    described in the user guides.

This contributor reference governs changes to the local OSS interface.
It is not a product roadmap or a guarantee that a proposed layout is released.
For the installed application, use the versioned user guides.

## Ownership and structure

- Projects group scientific work. Data selection, editable workflow state and
  retained run evidence are different objects; do not substitute one for another.
- A navigation action changes the view. It must not execute a workflow, mutate a
  dataset, change an exclusion or enable data sharing.
- Use the existing page header, context row, tabs and action components. Keep
  the selected object's name and compact scientific context visible.
- Use semantic theme tokens and the shared plot theme. Do not introduce
  component-local color authorities.
- Preserve keyboard access, visible focus and readable layouts at narrow widths.

## Scientific context and copy

Keep population, units, exclusions and consequential warnings visible.
Put methodology behind contextual `?` help, and short explanations in hover.
Omit redundant prose. A working plot is not evidence that its Data View works.

Technical IDs and digests remain accessible in details or copy actions; use
readable names for headings. Do not infer scientific identity from a display
label, a filename or matching row counts.

## State and operations

Loading, empty, unavailable and failed states have different meanings. Preserve
useful context during reads, reject stale responses, and offer a scoped retry.
Do not retry computation or a write merely because the user changed views.

Report and Inspector surfaces display retained evidence. Changing a current
workflow must not rewrite a saved run. Accepted background work retains its
own project/object identity; navigation is not a cancellation command.

## Product boundary

The OSS shell can host separately supplied extensions through its declared
contract. It must not import hosted implementation or represent an unavailable
managed capability as a working local control. Product-boundary notes should
be factual and brief.

## Verification

Use the [scientific result contract](scientific-result-surface-contract.md),
[theme authority](theme-authority.md), and
[scoped-state contract](scoped-workspace-state.md). Check both tables and plots,
exact identities and values, units, save/reopen and exports. A screenshot alone
cannot establish scientific correctness.
