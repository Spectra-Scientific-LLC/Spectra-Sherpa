# Week 7 Integration + Testing Checklist

This checklist is a manual runbook for the Week 7 integration flow. It assumes:
- Backend running: `poetry run uvicorn app.main:app --reload` in `Refactored/backend`
- Frontend running: `npm run dev` in `Refactored/frontend`
- API key set in Settings view (default: `default-local-key`)

## Experiments
- Create experiment with hardware + DOE + mixtures metadata.
- Upload a CSV to stage `raw` and confirm it appears in the files table.
- Create a version snapshot and confirm it appears in Version History.
- Restore the version and confirm the files list is still present.
- Export JSON, CSV, ZIP (validate file downloads).

## Builder
- Select experiment, choose uploaded file(s), run Preprocess.
- Confirm Plotly chart renders.
- Adjust preprocessing settings and re-run.
- Load any NIST library entry from NIST view (if available).
- Adjust curve editor points and blend weights, then run Blend.
- Export preprocessed spectra and blend result.

## Calibration
- Create calibration (compound name, concentration mode, x unit).
- Upload 4+ measurements with varying concentrations.
- Fit model (linear/saturation/hybrid) and watch job progress update.
- Confirm model version list updates and activate a model.
- Export calibration (JSON + CSV).

## NIST
- Search for a compound, confirm results populate.
- Trigger a download and watch job progress in queue.
- Confirm library table updates after completion.
- Load a library entry to Builder.
- Export library CSV.

## Chat
- Send a message, confirm streaming reply.
- Toggle metadata and send with a selected experiment.
- Use feature buttons (suggest name, peak ID, code gen, report) and confirm replies.
- Switch conversations and verify history.

## Jobs + Logs
- Open Logs view and refresh.
- Confirm job progress updates appear in NIST/Calibration flows.
