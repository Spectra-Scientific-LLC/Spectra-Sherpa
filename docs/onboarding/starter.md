# Start from a goal

The **Starter** tab, the first tab on the Dashboard, is for when you know what
you want to do but not which screen to open. It opens automatically the first
time you sign in.

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

Name the project and select **Ready to Start**. Starter creates the project
with your goal and plan and takes you to the first step.

## Follow the checklist

When the active project has a goal, the Starter tab shows it as a checklist.
Steps tick themselves off as you add data, build and run the workflow, and
save a model. **Go** opens the screen for the next step. A step that the app
cannot observe, such as reviewing results, is ticked once you open it or once
a later step is done.

The goal is part of the project. It is saved with project versions and
included when you export and import the project.

## On a managed deployment

Managed deployments can use the Advisor model to read goals that the keyword
rules do not recognise, and to choose among compatible datasets. The goal text
is sent to the model only when your AI disclosure setting allows it. The model
can only choose among the analyses and datasets Starter offers; the steps
themselves are always built by the app.

Ambient Guidance also follows the plan: its suggestions point to the next
unfinished step of the active project's goal. Guidance receives the kind of
analysis and the next step, never the text you typed.
