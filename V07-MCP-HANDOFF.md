# v0.7.0 OSS handoff

## Current checkpoint

The shared Workbench change is merged into OSS main at `f008773532409869b0f4fbcfe7980a89eba1ccd0`. The required Ubuntu CI, CodeQL analyses, and saved-model compatibility checks passed. [OSS PR #242](https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa/pull/242)

Data extension actions now use the selected raw file. They are available when a single raw file is selected and are hidden for named dataset views, unsaved sample curation, and unavailable views. This prevents an action from accidentally using the full file when the scientist is looking at a subset.

## Continue in a new session

For OSS work, select `Spectra-Scientific-LLC/Spectra-Sherpa` and base changes on `main`. This branch carries handoff notes.

The next checkpoint is the maintainer’s hosted Demo walkthrough. For that work, select the organization’s `spectra` monorepo and read `V07-MCP-HANDOFF.md` on `codex/v07-staging-handoff`. The monorepo handoff records the exact deployment revision and the staging walkthrough.
