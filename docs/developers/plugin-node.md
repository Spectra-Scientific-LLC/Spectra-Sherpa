# Writing a Plugin Node

A plugin node should be explicit about what it accepts and what it emits.

## Minimum Shape

- stable node type
- label and description
- parameters
- input ports
- output ports
- data-role expectations
- tests for successful and invalid wiring

## Scientific Rule

Do not make a node look more general than it is. A spectral preprocessing node should reject feature tables when it needs an ordered physical spectral axis.
