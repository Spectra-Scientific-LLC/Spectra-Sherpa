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
  the target. In **Data > Import > Reference Datasets**, find Corn M5, open its
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

1. Open **Workflow**, then **Analysis Starter**.
2. Pick **PLS Regression Calibration** and start it on the current data.
   The sheet contains: load data → Kennard–Stone train/test split (25 % test) →
   PLS with 3 latent variables and scaling → predict test set → held-out regression
   evaluation → metrics table and predicted-vs-actual plot.
3. Click **Run**. The run is saved in **Runs**.

The historical all-data development CV baseline was **RMSECV 0.2340 (n=80;
target units not declared)**.
Current Optimize evaluates this Rev0 by five-fold CV on its **60 training samples**;
the historical score is not an expected result for this training-only run.

## Step 2 — Choose the starting point

Open **Optimize**. It opens on the canvas of your most recent campaign. The title
is a menu of the project's campaigns; choose **New campaign** to start another.

1. Click **Select a starting point**. It lists the project's completed saved runs
   (its History); type part of a name to narrow the list.
2. Choose the Rev0 run. Opening **Optimize** from a run in **Runs** goes straight
   to the next step with that run.

## Step 3 — Set the ground rules (once per campaign)

In **Set the ground rules**:

1. **Spectral domain**: NIR.
2. **Outer folds**: 5.
3. **Meaningful improvement**: 0.01 (RMSECV; target units not declared in this historical example).
4. **Validation grouping**: **No grouping declared** (Corn M5 has one spectrum per
   sample; choose **Use retained group column** only for a true shared specimen,
   batch, or other group identity, including replicate measurements).
5. Tick **Use this objective, validation and grouping for every trial** and click
   **Start campaign**. Rev0 appears on the canvas, selected.

These settings are fixed for the whole campaign so every round is comparable;
**Inspect ground rules** shows them later.

## Step 4 — Round 1: explore preprocessing

1. With Rev0 selected, click **New hypotheses**.
2. **Search phase**: **Explore directions**. **Maximum candidates**: 3.
3. In the instruction box, say what to compare, for example:
   *"Compare SNV with a Savitzky–Golay first derivative before PLS."*
4. Click **Generate validated preview**. Sherpa proposes one hypothesis per change;
   each appears as a hollow dot on the canvas and in the list with **▸** for its
   **Rationale**, **Expected CV response**, **Trade-offs** and changes. Untick any
   you do not want, or **Revise validated preview** with a new instruction. The
   unchanged seed always runs as the reference.
5. Click **Execute selected models**. **Review plan** in the bottom bar shows the
   trial count, reserved evaluations and approval expiry if you want them first.

**Historical round 1 result** (5-fold all-data development CV, n=80, RMSECV):

| Trial | RMSECV (target units not declared; historical n=80) | Outcome |
|---|---|---|
| Rev0, unchanged | 0.2340 | reference |
| SNV before PLS | 0.2292 | not supported |
| **SG first derivative (window 15, order 2) before PLS** | **0.1369** | supported |

Each trial becomes a box under its hypothesis dot. Click a box for its CV score,
change against the parent, per-fold agreement and model changes; click its dot to
compare the boxes it produced (**Compare its seeds**). Failed or cancelled
evaluations do not constitute usable solutions. Ranking draws attention to
performance; it does not select a solution for you. Sherpa Advisor can retrieve
the campaign's CV evidence for whatever you select.

## The Optimize canvas

After a round runs, Optimize shows the campaign as a canvas:

- **Seed boxes** are models. Rev0 is the first box; every scored trial becomes a
  box, darker purple for a better score.
- **Hypothesis dots** sit between a seed and the boxes it produced. A half-filled
  dot is running, a hollow dot is a draft, and an orange ring did not meet its
  criterion. The legend inside the canvas repeats this.
- The **ranking** on the left lists every box best first; click a row to bring
  that box to the middle of the canvas.
- The panel on the right shows whatever you select. For a box: its lineage from
  Rev0, CV performance with per-fold bars, and the hypotheses grown from it. For a
  dot: the hypothesis, its success criterion, and the boxes it produced with their
  scores.
- The page subtitle carries the campaign facts (folds, held-out use, remaining
  rounds, best score, stop advice). **Inspect ground rules** shows the fixed
  objective, folds, meaningful improvement and grouping.
- The bar at the bottom holds running rounds (**View progress**, **Stop & keep
  results**), items that need attention, and messages.

**Classic layout** in the bottom bar switches back to the earlier page;
**Canvas layout** returns.

## Step 5 — Grow from the best direction

1. On the canvas, click the first-derivative box from round 1.
2. Click **New hypotheses** (top right). It is available only when a growable
   seed is selected.
3. Because this box has not been kept yet, say why: choose a reason (here
   **Primary metric**) and write a short rationale. Growing from it records the
   decision, and the box becomes **Rev1**.

## Step 6 — Round 2: refine from Rev1

1. In the same panel choose **Ask Sherpa**, **Search phase**: **Refine this
   direction**, **Maximum candidates**: 4.
2. Instruction, for example: *"Keep the derivative; try 4, 6 and 8 latent variables."*
3. **Generate validated preview**. The proposals appear as hollow dots on the
   canvas; untick any you do not want.
4. **Execute selected models** runs them. **Review plan** in the bottom bar shows
   the trial count, reserved evaluations and approval expiry if you want to check
   first; **Discard draft** leaves without running anything.

For a parameter or structure search instead, choose **Parameter search** or
**Workflow structure search** and **Set up search**. The search opens over the
canvas: pick the parameter values, recipes or governed lane, **Preview** the exact
candidates, then **Start search**; the new round appears on the canvas.

**Historical round 2 result** (all-data development CV, n=80), starting from Rev1:

| Trial | RMSECV (target units not declared; historical n=80) | Outcome |
|---|---|---|
| Rev1, unchanged | 0.1369 | reference |
| PLS 4 latent variables | 0.0899 | supported |
| PLS 6 latent variables | 0.0715 | supported |
| **PLS 8 latent variables** | **0.0549** | supported |

## Step 7 — Read the lineage and conclude

Click any box: the right panel shows its path from Rev0 (for the best round-2
box: Rev0 → derivative hypothesis → Rev1 → latent-variable search → the box).
The historical all-data CV lineage read 0.2340 → 0.1369 → 0.0549 RMSECV (n=80;
target units not declared). The subtitle's stop advice read **worth continuing**:
no two-round plateau and no uniform instability yet.

To conclude, select the box you trust and click **Conclude campaign**. Choose
**CV only** or **Independent confirmation**, confirm the freeze, and click
**Freeze final workflow and refit**. A CV-only conclusion cannot add independent
confirmation later in this campaign. When the conclusion is ready, **Open in
Workflow** opens the signed solution as a workflow sheet in your project;
executing it creates a saved run you can review in **Runs**. **Model package**,
**Report** and **Publisher keys** download the signed review. Concluding a
campaign is not a deploy-ready decision; that is recorded separately in
**Runs → Models**.

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

## Manual comparison in local OSS

Hosted Optimize campaigns require Demo or Pro. In local OSS, duplicate the
calibration workflow sheet, change one preprocessing or component setting at a
time, and execute each variant. Keep the same source selection, target, training
population, split seed, folds, and validation design across variants. Review
their saved evidence in **Runs** and record the comparison in **Report**.
Learn preprocessing inside training folds and preserve the test holdout for
final evaluation. The historical 0.2340 → 0.0549 figures above describe all-data
development CV on 80 samples; they are neither expected scores for current
training-only CV on 60 samples nor independent performance evidence.
