# Design of Experiments (DOE)

The **DOE** module manages high-throughput 96-well plate experiments, specifically designed for creating complex mixtures of Essential Oils (EO) and Standards.

## Data Structures

### Mixtures
A **Mixture** is defined by a set of components and their target proportions.
*   **Basis**: Mixtures can be defined by **Volume** (`vol`) or **Mass** (`mass`).
*   **Components**: Links to the `Sample` database (Pure Species).

### 96-Well Plate Map
The system uses a standard 8x12 grid (rows A-H, columns 1-12).
*   **Assignment**: Mixtures are assigned to specific wells.
*   **Replicates**: Multiple wells can contain the same mixture.

## Sample Database
The database tracks:
*   **Type**: `essential_oil`, `carrier`, `standard`.
*   **Metadata**: Brand, CAS Number, Lot Number.

## Acquisition Matching

This feature links physical filenames to logical well positions.

### Auto-Matching Logic
The matcher parses filenames using common patterns to extract:
1.  **Well Position**: Looks for patterns like `RowA_Col1`, `A1`, `B12`.
2.  **Sequence**: Extract run numbers (e.g., `_001`, `_002`).

### Data States
*   **Raw**: The original file as uploaded.
*   **Matched**: Linked to a specific Well and Mixture.
*   **Processed**: Associated with a generic workflow result.

## Calibration DOE (Project 1)

For calibration studies, the DOE configures:
*   **Factors**: Variables like `Concentration`, `Temperature`, `IntegrationTime`.
*   **Levels**: Specific values for each factor (e.g., [0, 10, 50, 100] ppm).
*   **Run Sequence**: A generated list of runs (combinations of factor levels).

When loading data for these experiments, the system attempts to parse the filename to identify the specific run index and associate the correct factor values with the spectra.