# Experiment Management

The **Experiments** module is the central hub for managing spectral data. It handles versioning, metadata tracking, and organization of your experimental datasets.

## Creating a New Experiment

1.  Navigate to **Experiments** in the sidebar.
2.  Click the **Create** tab.
3.  Fill in the details:
    *   **Name**: A unique, descriptive name.
    *   **Description**: Experimental goals and notes.
    *   **Hardware**: (Optional) Spectrometer details.
    *   **DOE Setup**: (Optional) Link to a Design of Experiments configuration.
4.  Click **Create Experiment**.

## Uploading Files

Once an experiment is created, you can add data:
1.  Select the experiment from the **Overview** tab.
2.  Switch to the **Files** tab.
3.  Select the data stage:
    *   **Raw**: Unprocessed instrument outputs.
    *   **Preprocessed**: Data after baseline correction, etc.
    *   **Synthetic**: Generated spectra.
4.  Drag & drop files or browse to upload.
    *   *Supported Formats*: CSV, JCAMP-DX (.jdx), SPC, SpectroChemPy formats.

## Version Control

SpectraSherpa tracks changes to your datasets:
1.  Go to the **Versions** tab.
2.  Click **Create Version** to snapshot the current state.
3.  Restore previous versions anytime using the restore icon.

## DOE Calibration Data

For calibration studies (Project 1), you can configure detailed experimental factors:
*   **Sample Factors**: Concentration, ratios, types.
*   **Method Factors**: Temperature, integration time.
*   **Run Sequence**: Define the exact order and conditions of your runs.

Files uploaded to these experiments can be automatically matched to their run conditions in the **Acquisition Matching** section.
