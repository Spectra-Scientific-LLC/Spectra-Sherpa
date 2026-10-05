# Optimize a Saved Result (Demo and Pro)

Optimize turns one saved calibration run into a sequence of small, reviewed
experiments. Each round tests a few changes against the workflow it started from,
on the same cross-validation folds. You keep the change you trust, and the next
round starts from it.

This guide walks one complete journey on the Corn M5 moisture data: a stock PLS
calibration (Rev0), a first round that compares preprocessing, and a second round
that tunes latent variables on the scientist's selected solution. The numbers
are historical **all-data development CV on 80 Corn samples**, not proof that the
current deployment passed release qualification. Current campaigns preserve the
25% test holdout and tune only the 60 training samples; reruns will produce different
scores. The 20 test samples are reserved for inspection.

!!! note "Availability"
    Optimize is part of the hosted Demo and Pro profiles. It appears in the
    navigation only when the deployment's campaign service is accepting work.
    Review the proposed changes before executing. Remaining campaign rounds are
    an allowance ceiling, not a reservation of shared infrastructure. There is no
    pre-execution forecast of compute hours or infrastructure cost. The service
    checks recorded resource use before starting: exhausted configured thresholds
    refuse the start with an alarm. A round admitted below those thresholds may
    finish even if it crosses them; per-round safety limits still apply.

## Before you start

- A project with the **Corn M5** reference dataset imported, with **Moisture** as
  the target. In **My Dataset**, find Corn M5 in the reference catalog, open its
  **Provider page** to download the archive, then choose **Import downloaded file**.
  SpectraSherpa checks the file against its registered fingerprint and binds the
  spectra (1100–2498 nm, 80 samples) and the Moisture values.
- An active account, any required trial-policy acceptance, an owned project and
  an eligible saved run with retained source evidence. Trial expiry, scientific
  safety checks, shared limits and operator pauses remain legitimate gates.
  Optimize never changes your saved run.

### Supported data and qualification

OZCAM supports NIR and FTIR sources with retained technique metadata and a spectral
axis. Choosing NIR or FTIR in the form does not convert a tabular dataset into
spectroscopy. Scikit-learn examples and other modalities are outside this scope.
If metadata is missing, correct the source/import and run it again rather than
guessing its identity.

The reference offering includes 13 registered Eigenvector NIR projections, the
50-spectrum synthetic atmospheric FTIR example (Carbon dioxide regression), and
the 33-spectrum lavender essential-oil FTIR corpus (classification). Eigenvector
archives require acquisition from the provider and fingerprint-checked import;
they are not redistributed merely because their catalogue cards are visible.
Catalogue and import qualification do not establish successful optimization for
every target, grouping choice, model, or deployment. Release validation records
each actual dataset/profile journey separately.

!!! note "For newer users"
    Lavender's `block` is a retained acquisition-group column, not a request to
    block execution. Use grouping when your scientific question requires keeping
    related spectra together; do not invent a group column to satisfy the form.
    Public reference results demonstrate reproducibility, not production-method
    performance or independent validation of your own samples.

## Step 1 — Build and save Rev0

Rev0 is the result you want to improve. Here it is the stock calibration starter,
unchanged.

1. Open **Workflow**, then **Choose Analysis Starter**.
2. Pick **PLS Regression Calibration** and start it on the current data.
   The sheet contains: load data → Kennard–Stone train/test split (25 % test) →
   PLS with 3 latent variables and scaling → predict test set → held-out regression
   evaluation → metrics table and predicted-vs-actual plot.
3. Click **Execute Workflow**. The run is saved in **Results**.

The historical all-data development CV baseline was **RMSE 0.2340 (n=80)**.
Current Optimize evaluates this Rev0 by five-fold CV on its **60 training samples**;
the historical score is not an expected result for this training-only run.

## Step 2 — Open the campaign planner

You can start from the run or from Optimize itself; both open the same planner.

- From the run: open it in **Results** and choose **Optimize**.
- From Optimize: click **New campaign** → **A saved run** → choose the project and
  the saved run → **Continue with Sherpa**.

The planner shows **Rev0** at the top, with **Inspect run**, **Open workflow** and
the **Original validation**.

## Step 3 — Frame the development question (once per campaign)

Under **Frame the development question**:

1. **Spectral domain**: NIR.
2. **Common outer folds**: 5.
3. **Meaningful improvement**: 0.01 (RMSE units of moisture).
4. **Validation grouping**: **No grouping declared** (Corn M5 has one spectrum per
   sample; choose **Use retained group column** when you have replicates).
5. Tick **Confirm this objective, validation, and grouping as the common development
   examination**.
6. Click **Start planning from Rev0**.

These settings are fixed for the whole campaign so every round is comparable.

## Step 4 — Round 1: explore preprocessing

1. **Search phase**: **Explore directions**.
2. **Maximum candidates including Rev0**: 3.
3. In the instruction box, say what to compare, for example:
   *"Compare SNV with a Savitzky–Golay first derivative before PLS."*
4. Click **Generate validated preview**. Sherpa proposes one hypothesis per change and
   shows, for each: **Why Sherpa thinks this is worth testing**, **Expected
   development evidence**, **Trade-offs to inspect** and the **Exact workflow change**.
   Use **Revise validated preview** to adjust.
   You can also turn individual hypotheses off: excluded cards turn grey, and the
   reviewed execution covers only the selected hypotheses plus the unchanged baseline. For
   example, selecting 10 of 15 hypotheses means 11 evaluations. The baseline stays
   selected. If you remove part of a coordinated experimental design, the warning
   explains that the remaining trials are exploratory, not a validated full DOE.
5. Click **Review selected trials**. In **Reviewed execution plan**, check the
   selected trials, unchanged baseline, execution safety limits and **Approval receipt expires**.
   This approval is not a compute-hours or cost forecast.
6. Click **Execute reviewed iteration**. The page opens the campaign's progress in
   **Optimize** (or click **View progress**).

**Historical round 1 result** (5-fold all-data development CV, n=80, RMSE):

| Trial | RMSE | Outcome |
|---|---|---|
| Rev0, unchanged | 0.2340 | reference |
| SNV before PLS | 0.2292 | not supported |
| **SG first derivative (window 15, order 2) before PLS** | **0.1369** | supported |

The monitor shows the evaluations, best RMSE against the starting point, the trend,
and successfully evaluated candidates with **Open in Workflow** to inspect them as
normal sheets. Failed or cancelled evaluations do not constitute usable solutions.
Ranking draws attention to performance; it does not select a solution for you.

## Step 5 — Keep the best direction

1. In Optimize, choose **New campaign** → **A solution from a campaign** → select the
   round-1 campaign → **Open campaign plan**. (Or return to the planner.)
2. Under **Iterative development**, find iteration 1 and the first-derivative trial.
3. Choose a reason (here **Primary metric**), write a short rationale, and click
   **Retain as refined seed**. The trial becomes **Rev1**, recorded with its evidence.

## Step 6 — Round 2: refine from Rev1

1. Under **Seed history**, click **Plan another direction from Rev1**.
2. **Search phase**: **Refine this direction**. **Maximum candidates including Rev0**: 4.
3. Instruction, for example: *"Keep the derivative; try 4, 6 and 8 latent variables."*
4. **Generate validated preview** → **Review selected trials** →
   **Execute reviewed iteration**.

**Historical round 2 result** (all-data development CV, n=80), starting from Rev1:

| Trial | RMSE | Outcome |
|---|---|---|
| Rev1, unchanged | 0.1369 | reference |
| PLS 4 latent variables | 0.0899 | supported |
| PLS 6 latent variables | 0.0715 | supported |
| **PLS 8 latent variables** | **0.0549** | supported |

## Step 7 — Read the lineage

Select the round-2 campaign in Optimize. The historical all-data CV **Lineage** showed:

- Baseline · RMSE 0.2340
- Seed 0 · saved run → Round 1 · explore · best RMSE 0.1369 · improved 0.0971 on parent
  - Seed 1 · promoted → Round 2 · refine · best RMSE 0.0549 · improved 0.0820 on parent

Click any round to open it. Below the tree, the stop advice for this run read
**Worth continuing**: no two-round plateau and no uniform instability yet.

## What these numbers mean

- Each round re-scores its own starting point on the same folds, so the
  improvement shown is like-for-like.
- These historical figures are **all-data development CV** scores on 80 samples. Picking the best of several trials
  flatters the winner. Before using the 8-latent-variable model, confirm it on
  independent data: the planner's **Independent confirmation** step does this once,
  against a protected benchmark you name.
- A round that finds nothing better is a valid answer, not an error. Keep the
  previous seed and try a different direction or stop.

## Stopping and cancelling

- **Stop & keep results** ends a running round; finished evaluations are kept.
- **Cancel** in the campaign header stops the displayed campaign only.
