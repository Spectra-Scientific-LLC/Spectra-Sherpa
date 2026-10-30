# Start from a goal

!!! abstract "Summary"
    The Starter tab turns a sentence about what you want to do into a suggested analysis, a compatible dataset, and a checklist that tracks your progress. It opens automatically the first time you use the app and is the easiest way to begin.

The **Starter** tab, the first tab on the Dashboard, is for when you know what
you want to do but not which screen to open. Open it from the Dashboard; local OSS requires no sign-in.

## Describe your goal

Type what you want to do in your own words, for example:

- "Smooth my spectra and correct the baseline so I can compare samples"
- "Predict moisture in my corn NIR spectra"
- "Find the peaks in my Raman spectra"

The box starts with the last goal you entered, or with a suggested goal on
your first visit. The example buttons under the box fill in a typical goal for
each kind of analysis.

Select **Plan my steps**. Starter picks:

- **The kind of analysis**: clean up and transform spectra, explore and
  compare samples, find peaks, predict a value, sort samples into classes,
  group similar samples, or separate mixture components.
- **A starter workflow** that is available in your installation for that
  analysis.
- **A dataset to begin with.** If your goal names a material, technique or
  property ("corn", "NIR", "moisture"), Starter suggests a matching dataset
  and says why. It looks at the reference catalog and, when running locally,
  at your own datasets that are not in a project yet. Only datasets
  that work with the starter workflow are offered. Without a match it suggests
  a bundled practice dataset. You can choose another dataset, or, when running
  locally, import your own files instead.
- **The steps**, from adding data to reviewing results. Select a step to read
  what it involves.

When a project is already open, **Start another project** creates a separate
project and preserves the current project’s goal. **New Analysis** remains on
**Dashboard → Your Project**, rather than the Starter subtab.

Name the project and select **Ready to Start**. Starter creates the project
with your goal and plan and takes you to the first step.

## Follow the checklist

When the active project has a goal, the Starter tab shows it as a checklist.
Steps tick themselves off as you add data, build the workflow and complete a
run. **Go** opens the screen for the next step.

- **Only a completed run counts.** If the last run failed, stopped partway or
  was cancelled, the Run step stays open and offers **See what went wrong**,
  which opens the run so you can fix the step it names before running again.
- **Steps the app cannot observe**, such as reviewing the results, stay open
  until you select **Mark done**. Saving a model does not tick the review step:
  check the predictions or validation first. **Undo** reopens a step you
  marked by mistake. Marking a step done is saved with the project.

The starter workflow follows you through the steps. Whether you start from a
reference dataset, one of your own datasets or files you upload, the template
picker opens on the planned starter once you send your data to Workflow.

The goal is part of the project. It is saved with project versions and
included when you export and import the project.

## Hosted boundary

Local goal planning uses the installed analysis and dataset rules. Managed
Advisor-assisted planning and Guidance belong to separate hosted services;
they are not required to use Starter locally.
