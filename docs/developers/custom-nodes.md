# Custom Nodes

!!! abstract "Summary"
    Turn your own Python function into a workflow node in local Workbench, without forking Spectra Sherpa. You own the science of your nodes.

A custom node is a plain Python function with one decorator. Workbench turns it
into an ordinary node: it appears in the palette, takes bounded parameters,
runs in the same engine and workers as built-in nodes, and records exactly
which code produced each result. This page is written so a scientist or a
coding agent can convert an existing function without reading anything else.

Custom nodes are a local feature. They load only in local Workbench (not the
desktop shell, Demo or hosted Pro), and only after you turn them on.

## Five-minute quickstart

1. **Turn custom nodes on.** In **Settings → Integrations → Custom nodes**,
   select **Load custom nodes**. The section shows your My nodes folder, by
   default `<data folder>/user/my_nodes/`.
2. **Create a source folder** inside My nodes, for example
   `my_nodes/whitaker_hayes/`, and save this file in it as `whitaker_hayes.py`:

```python
from typing import Annotated

import numpy as np

from spectra_sherpa.sdk.custom import Spectra, custom_node, param


@custom_node(label="Whitaker-Hayes despike", category="preprocessing")
def despike(
    spectra: Spectra,
    threshold: Annotated[float, param(min=3.0, max=20.0)] = 6.0,
    window: Annotated[int, param(min=1, max=10)] = 2,
) -> Spectra:
    """Flag spikes by the modified z-score of first differences and replace each
    flagged point with the mean of its unflagged neighbours (Whitaker and Hayes, 2018)."""
    x = spectra.values
    out = x.copy()
    for row in range(x.shape[0]):
        delta = np.diff(x[row])
        mad = np.median(np.abs(delta - np.median(delta))) or 1e-12
        z = 0.6745 * (delta - np.median(delta)) / mad
        spikes = np.zeros(x.shape[1], dtype=bool)
        spikes[1:] = np.abs(z) > threshold
        for j in np.flatnonzero(spikes):
            lo, hi = max(0, j - window), min(x.shape[1], j + window + 1)
            neighbours = [k for k in range(lo, hi) if not spikes[k]]
            if neighbours:
                out[row, j] = x[row, neighbours].mean()
    return spectra.with_values(out)
```

3. **Check it** before restarting:

```bash
spectra-sherpa nodes check ~/path/to/my_nodes/whitaker_hayes
```

   The check imports the folder the way Workbench does, validates every
   declaration, and runs each node once on a small bundled example dataset.
4. **Restart Workbench.** Settings lists each source and whether it loaded.
5. **Use it.** "Whitaker-Hayes despike" appears in the palette under
   Preprocessing. Its type is `user.whitaker-hayes.despike`.

## Convert your function

The decorator reads everything from the function itself:

- **Label and category** come from `@custom_node(label=..., category=...)`.
  Categories are `preprocessing`, `exploratory`, `selection` and `output`.
- **Help text** is the docstring.
- **Data in and out** come from the type hints: `Spectra` (copied values with
  their feature axis and units) or `numpy.ndarray` (samples × features values
  only).
- **Parameters** are the remaining arguments. Each needs a default.

Your function never sees the dataset behind the spectra: no reference values,
groups, sample labels or history. Workbench rebuilds the output from its own
copy of the samples, axis and units, so they are always kept exactly.

### A numpy preprocessing function

If your function takes and returns a plain array, annotate both as
`np.ndarray`. Workbench keeps the samples, axis and units for you.

```python
from typing import Annotated

import numpy as np

from spectra_sherpa.sdk.custom import custom_node, param


@custom_node(label="Moving median", category="preprocessing")
def moving_median(
    values: np.ndarray, width: Annotated[int, param(min=3, max=51, odd=True)] = 5
) -> np.ndarray:
    """Replace each point with the median of an odd-width window; edges use the available points."""
    half = width // 2
    out = np.empty_like(values)
    for column in range(values.shape[1]):
        lo, hi = max(0, column - half), min(values.shape[1], column + half + 1)
        out[:, column] = np.median(values[:, lo:hi], axis=1)
    return out
```

### A step that uses the axis

Use `Spectra` when the method needs the feature coordinates or units.
`spectra.axis` is a copy of the coordinates; `spectra.with_values(...)` returns
the same spectra with new values of the same shape.

```python
from typing import Literal

import numpy as np

from spectra_sherpa.sdk.custom import Spectra, custom_node


@custom_node(label="Area normalize", category="preprocessing")
def area_normalize(spectra: Spectra, area: Literal["absolute", "signed"] = "absolute") -> Spectra:
    """Divide each spectrum by its integrated area over the feature axis."""
    values = spectra.values
    axis = spectra.axis if spectra.axis is not None else np.arange(values.shape[1], dtype=float)
    integrand = np.abs(values) if area == "absolute" else values
    totals = np.sum((integrand[:, 1:] + integrand[:, :-1]) / 2 * np.diff(axis), axis=1)
    if np.any(totals == 0):
        raise ValueError("A spectrum has zero area and cannot be normalized")
    return spectra.with_values(values / totals[:, None])
```

### A step that keeps only some features

Cropping and derivative edges change the number of features. Declare
`changes_features=True`, choose the features with `select_features(...)` (a
slice, boolean mask or increasing positions), then set the values. The kept
features keep their coordinates.

```python
import numpy as np

from spectra_sherpa.sdk.custom import Spectra, custom_node


@custom_node(label="First derivative (interior)", category="preprocessing", changes_features=True)
def first_derivative(spectra: Spectra, edge: int = 2) -> Spectra:
    """Central first derivative; the outer edge points are dropped rather than extrapolated."""
    values = spectra.values
    derivative = np.gradient(values, axis=1)
    kept = spectra.select_features(slice(edge, values.shape[1] - edge))
    return kept.with_values(derivative[:, edge : values.shape[1] - edge])
```

### Fitted steps and reference values

Steps that fit on training data, or read reference values or groups, are not
available in this release. `fits=True`, `uses_target=True` and
`uses_groups=True` are refused with a message, and so are `changes_rows` and
`changes_axis`. Use the SDK for that work in the meantime.

## Defaults and opt-ins

| Behavior | Default | Opt-in |
| --- | --- | --- |
| Samples (rows) | All kept, same order | Not available in this release |
| Features | All kept | `changes_features=True` with `select_features(...)` |
| Axis and units | Kept | Not available in this release |
| Reference values and groups | Not visible | Not available in this release |
| State | Stateless; nothing is fitted | Not available in this release |
| Determinism | Deterministic | `random_seed="seed"` names an int `seed` parameter |
| Resources | 60 s, 1024 MB | `timeout_seconds=...`, `memory_mb=...` |

Defaults are **checked on every run**, not just documented. A node that returns
a different number of samples, changes features without declaring it, or
returns NaN or infinite values fails with a message naming the fix.

## Parameters

| Annotation | Palette control | Checks |
| --- | --- | --- |
| `int` | Number, step 1 | Whole number; `param(min=, max=, odd=True)` |
| `float` | Number | Finite; `param(min=, max=)` |
| `bool` | Switch | True or false only |
| `Literal["a", "b"]` or `param(choices=...)` | Select | One of the choices |

Out-of-range or wrong-type values are refused, never silently corrected. Use
`param(label=..., description=...)` for the palette label and hover text.

## Where custom nodes come from

**My nodes folder.** Each subfolder of My nodes is one *source*. Every `.py`
file at the top of the subfolder is imported on its own, so keep a node and its
helpers in one file. Every file in the subfolder, including notes or small
data files, is part of the source's recorded build. Keep large data out of it.

**Installed packages.** To share nodes through `pip`, put them in a package and
declare an entry point naming a module inside a package directory:

```toml
[project.entry-points."spectra_sherpa.custom_nodes"]
lab_nodes = "lab_nodes.despike"
```

Install the package into the same environment as Spectra Sherpa and restart.
The source name is the package name, and Settings shows its version.

**Names.** A node's type is `user.<source>.<function>`, for example
`user.whitaker-hayes.despike` for the folder `whitaker_hayes` or
`user.lab-nodes.despike` for the package `lab-nodes`. Moving a node between a
folder and a package changes its type; re-select it in saved workflows.

Two sources with the same name are both refused, and Settings names them.

## What is recorded

Every output a custom node produces records, in its processing history, the
source name and version, the SHA-256 of all the source's files, and the node's
execution-contract digest, which includes the digest of its module. Runs
therefore show exactly which code produced each result.

Workbench compiles each custom-node file from the exact bytes it records,
never from cached bytecode. Editing a node changes these digests for later runs; earlier runs keep theirs.
If a saved workflow uses a custom node whose source is missing, the workflow
check names the node and tells you to restore the folder or package, turn on
custom nodes and restart. Changes take effect on restart, like an upgrade, and
spawned workers verify that they load exactly the same nodes as Workbench.

Custom nodes are not offered by the assistant's workflow proposals or by
managed optimization, and they cannot be exported to Python or as a released
application in this release.

## Error messages and fixes

| Message | Fix |
| --- | --- |
| `... changed the number of features; declare changes_features=True ...` | Declare the opt-in and return `spectra.select_features(...).with_values(...)`. |
| `... must keep every sample` | Return one row per input sample, in order. |
| `... returned NaN or infinite values` | Handle edge cases (division by zero, empty windows) in your function. |
| `... must return the spectra it received ...` | Return `spectra.with_values(...)`, not a new `Spectra(...)`. |
| `with_values() needs an array of shape ...` | Return values of the same shape, or select features first. |
| `Parameter 'x' needs a default value` | Give every parameter after the first a default. |
| `The first argument must be annotated as Spectra or numpy.ndarray` | Annotate the data argument and the return value. |
| `fits=True is not available in this release ...` | Remove the opt-in; use the SDK for fitted steps for now. |
| `No @custom_node functions were found` | Decorate at least one top-level function in the source. |
| `SystemExit: the source exited while importing ...` | Move script code such as `argparse` or `sys.exit()` under `if __name__ == "__main__":`. |
| `... changed while it was loading` | Save your edits, then restart Workbench. |
| `Two sources use the name ...` | Rename one folder or package. |

## Checklist for coding agents

1. Keep the user's function signature and body; add only the decorator, type
   hints and parameter bounds.
2. Annotate the first argument and the return value as `Spectra` or
   `np.ndarray`. Use `Spectra` only when the axis or units are needed.
3. Give every other parameter a default, a type from the parameter table, and
   bounds that reflect the method, not convenience.
4. Write the docstring as the help text: what it does, the method and its
   citation, and its limitations.
5. Declare only the opt-ins the function really needs.
6. Put the file in its own subfolder of My nodes, with nothing large beside it.
7. Run `spectra-sherpa nodes check <folder>` and fix every reported failure.
8. Test the science yourself against an independent calculation; the check
   proves the contract, not the method.

## Licensing

Custom nodes import Spectra Sherpa, which is licensed under the
[GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html).
Consider its terms before distributing a custom-node package.

For a reviewed, first-party node in Spectra Sherpa itself, see
[Adding a Scientific Node](adding-a-node.md).
