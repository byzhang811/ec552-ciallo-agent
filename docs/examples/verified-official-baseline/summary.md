# E. coli Compact Biosensor

## Request Summary

Design a compact E. coli biosensor using the official library and output YFP.

## Selected Official Library

- Version: Eco1C1G1T1
- Chassis: Eco
- Organism: Escherichia coli NEB 10-beta
- Sensors: LacI_sensor, TetR_sensor
- Output device: YFP_reporter

## Logic

The biosensor activates YFP expression in response to the presence of the input signal controlled by LacI.

## Constraints

- Review gate count, chassis fit, and reporter compatibility before compilation.

## Validation Checklist

- Check for proper sensor availability in Eco chassis.
- Verify YFP output functionality.
- Validate generated input/output/UCF JSON files against the official Cello schemas.
- Confirm the chosen library has enough compatible sensors and reporter devices.
- Run Docker-based Cello compilation and inspect generated output artifacts.

## Manual Review Notes

- None
