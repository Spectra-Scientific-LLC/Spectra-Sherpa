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
- Storage recovery belongs to Settings, not the scientific project dashboard.
  Legacy navigation must redirect without initiating reclamation.

## Plate maps

Hover updates belong to the details card, not the cell grid. Keyboard focus
keeps its details through automatic scrolling while the focused well remains
visible; a stationary pointer must not replace that context during the pan.

The shared format registry (`src/spectra_sherpa/data/plate_formats_v1.json`)
owns plate geometry and coordinates. API schemas, planning, sample tables and
the shared plate renderer derive from it. Keep legacy tables without an explicit
format on their historical 96-well interpretation; overlapping coordinates do
not establish another plate's size.

Use fixed-size wells and text inside a two-axis scroll viewport. Row labels stay
at the left and column labels at the top, aligned with their wells while panning.
Do not shrink text to fit high-density plates or leave a floating tooltip anchored
to a well that has scrolled away. Format changes must not silently hide or discard
existing assignments.

Format admission covers planned wells and retained acquisition matches through
the same coordinate authority used by measured-sample tables. Parse distinct
well coordinates once when deriving format choices; unrelated field edits must
not repeat that work. Keep a malformed current assignment repairable, but do not
admit it for publication. A refused synchronization proposal is a conflict, not
a publishable change or evidence that the populations are synchronized.

Data source subtabs (Import, Synthesis, Upload, Library and Multi-well) end in
the existing My Dataset action; My Dataset alone offers the Workflow handoff.
Keep Synthesis/Library Guide and Upload Load beside that header action, not in
separate toolbar rows. Library's filtered entry count belongs in the subtitle;
Database precedes its source dropdown. Import's selected title belongs in the context strip;
its preview sections align with the catalog rather than repeat the title.

## Scientific context and copy

Descriptive source summaries can report finite coordinate bounds and recorded
catalog bounds, with their origin and missing-coordinate counts. They do not
authorize rendering or weaken the strict plot-axis alignment validator.

Keep population, units, exclusions and consequential warnings visible.
Put methodology behind contextual `?` help, and short explanations in hover.
Omit redundant prose. A working plot is not evidence that its Data View works.

Lead results pages with plots and a compact model/population strip; put exact
tables and implementation identity under named disclosures. Keep unavailable CV,
requested-versus-fitted component differences, and calibration-only limitations
outside collapsed details. Successful QC checks may collapse together; actual
warnings must remain visible. Empty downstream synthesis sections may start
collapsed, but users must still be able to open them without a forced wizard.

Use one accessible `MethodHelp` control for each coherent explanation. Do not
replace removed paragraphs with hover-only instructions or a second help system.
Preserve scientific scope in offline reports; reducing setup-page copy does not
authorize removing evidence from exports.

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
