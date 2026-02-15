# Server Operator Guide

SpectraSherpa can be deployed as a multi-user server or a hybrid cloud extension. This guide covers the operational details for **Hybrid** and **Enterprise** modes.

## Deployment Modes

| Mode | Target User | Authentication | Network Egress | Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Local** | Individual | None | Disabled (Opt-in) | Personal research, offline analysis. |
| **Hybrid** | Organizations | By IP / Loopback | Enabled | GPU offload, centralized identity management. |
| **Enterprise** | Public / Cloud | JWT Required | Enabled | Evaluation, training, public demos. |

## Which Mode Should I Run?

- **Run Hybrid Mode** if you are a research group wanting a central compute server that team members can connect to from their local clients.
- **Run Enterprise Mode** if you are hosting a public-facing instance (e.g., on DigitalOcean) for users to try out the software without installing it. Set `SITE_PROFILE=demo` to display demo branding on the login page.
