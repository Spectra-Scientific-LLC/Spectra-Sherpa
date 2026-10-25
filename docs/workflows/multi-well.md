# Multi-well Experiments

Use **Data > Multi-well** to record what should be measured and where, then
review the relationship between that plan and the acquired files in **My Dataset**.
This workspace records acquisition intent; it does not control an instrument.

## Choose the dataset and plate

Select the dataset the plan belongs to. Its name is the same reference used in
My Dataset. Choose the plate format explicitly:

| Wells | Rows × columns | Last well |
| --- | --- | --- |
| 6 | 2 × 3 | B03 |
| 12 | 3 × 4 | C04 |
| 24 | 4 × 6 | D06 |
| 48 | 6 × 8 | F08 |
| 96 | 8 × 12 | H12 |
| 384 | 16 × 24 | P24 |
| 1536 | 32 × 48 | AF48 |

Settings supplies the default for new plans and new measured-sample tables.
Saved plans and tables retain their own format; legacy tables without a declared
format use 96 wells. Occupied wells alone do not establish the plate format.
Changing format must also accommodate retained acquisition matches.

Scroll large plates horizontally or vertically. Well text and hover text keep
their size, while row and column headers remain visible. Keyboard users can
enter the plate once and move with arrow keys; Home/End move within a row and
Ctrl+Home/End move to the first/last eligible well.

## Record the acquisition plan

Work through the seven sections:

1. **Samples:** enter stable sample IDs, readable names and sample types.
2. **Mixtures:** define components, amounts, units and mass or volume basis.
3. **Factors:** declare sample or method factors and their levels.
4. **Plate layout:** assign samples or mixtures to wells; unused wells may remain empty.
5. **Acquisition order:** record method run levels, sequence, paths and batches.
6. **Acquisition matching:** set the filename pattern, first well and scan direction,
   or apply an available retained preset. Saved matches take precedence; unmatched
   measured rows use planned plate order.
7. **Review:** check counts and synchronization state, then **Save acquisition plan**
   when there are changes.

Saving the plan does not change the measured sample table or earlier results.
Planned mixture amounts are intended preparation values, not independent
laboratory measurements of a response.

## Review acquired data in My Dataset

1. Load the acquired files and open the corresponding dataset in **My Dataset**.
2. Open its measured-sample editor and choose **Use acquisition plan** when available.
3. Review the proposed file/sample/well assignments and before/after differences.
   Resolve missing or conflicting matches instead of treating plate order as
   proof of specimen identity.
4. **Apply proposal** to the draft only after checking it. This is not publication.
5. Review the draft and choose **Publish new immutable version** to retain the
   measured-sample table. Previous versions and runs remain unchanged.
6. Confirm target, units, grouping and inclusion in My Dataset, then
   [save a portfolio](data-import.md#build-a-portfolio-in-my-dataset) and open Workflow.

Wells identify positions, not independent specimens. If several wells measure
the same specimen, retain that specimen's group identity when designing
[validation](../chemometrics/validation-design.md).
