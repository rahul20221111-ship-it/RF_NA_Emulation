# RF Network Analyzer Emulation using Signal Generator and Spectrum Analyzer

This project presents a Python-based RF measurement system that emulates basic Network Analyzer (NA) functionality using a Signal Generator and a Spectrum Analyzer. The system eliminates the need for expensive Vector Network Analyzers (VNAs) and directional couplers by utilizing computational post-processing and live RF spectrum analysis.

The software provides real-time frequency sweep measurements, automatic VISA instrument detection, live spectrum visualization, CSV data export, and automatic span/center-frequency synchronization between instruments.

## Features

- Live RF spectrum plotting
- Automatic VISA device detection
- Automatic span and center frequency adjustment
- dBm and mW visualization
- CSV data export
- Real-time RF sweep analysis
- Automatic step-size optimization based on sweep span

## Instruments Used

### Spectrum Analyzer
- Keysight N9912C FieldFox Spectrum Analyzer

### Signal Generator
- Rohde & Schwarz SMC100A RF Signal Generator

## Software Requirements

```bash
pip install numpy pyvisa PyQt6 matplotlib
```

## Run the Software

```bash
python main.py
```

## Output

The software provides:

- Live RF Spectrum visualization
- Power vs Frequency analysis
- Reflection analysis due to impedance mismatch
- CSV export of measurement data


## Research Pre-Print

The complete research manuscript is publicly available on Zenodo:

https://zenodo.org/records/17100248


## Citation

If this work contributes to your research or academic work, please consider citing the repository and associated manuscript appropriately.


## Author

**Rahul Das**  
Indian Institute of Science Education and Research (IISER) Tirupati
