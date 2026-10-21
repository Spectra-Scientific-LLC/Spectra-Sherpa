# Choose your working surface

The local Workbench and Python SDK use the same canonical scientific nodes.
Choose a surface, not a different implementation of the calculation.

| Surface | Use it for | Start here |
| --- | --- | --- |
| Local Workbench | Interactive data inspection, workflows, saved results and reports | [Local onboarding](local-30-minutes.md) |
| Python or Jupyter | Scripted workflows, reproducible notebooks and supported exports | [Python workflows](python-canonical-workflows.md) |
| Desktop application | The local Workbench in a native window, when matching installers are published | [Check installer availability](../support/local_install.md) |

These guides describe the v0.6.4 candidate, which is not yet published.
Use an exact reviewed source revision for candidate testing. A source tag,
PyPI wheel and desktop installer are different artifacts.

Choose SCP, HITRAN and NIST dependencies up front in the local installation
guide. Offline scientific calculation does not require an AI key or account.
Optional network acquisition and chat have their own configuration and terms.

Managed Demo/Pro are separate hosted offerings. Their Advisor, Optimize,
accounts and usage policies are not installed by the OSS package.
See [Product boundaries](../introduction/cloud-vs-local.md).
