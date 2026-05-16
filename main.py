import sys
import threading
import time
import numpy as np
import pyvisa
import csv

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox
)

from PyQt6.QtCore import pyqtSignal, QObject

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from pathlib import Path


class Communicate(QObject):
    data_signal = pyqtSignal(np.ndarray, np.ndarray)
    finished_signal = pyqtSignal()


class LivePlotCanvas(FigureCanvas):

    def __init__(self):
        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        super().__init__(self.fig)

        self.ax.set_title("Live RF Spectrum (dBm)")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_ylabel("Power (dBm)")

        self.line, = self.ax.plot([], [], 'b-')

        self.ax.grid(True)
        self.fig.tight_layout()

    def update_plot(self, freqs, powers):
        self.line.set_data(freqs / 1e6, powers)

        self.ax.relim()
        self.ax.autoscale_view()

        self.draw()


class LivePlotCanvasMW(FigureCanvas):

    def __init__(self):
        self.fig, self.ax = plt.subplots(figsize=(8, 3))
        super().__init__(self.fig)

        self.ax.set_title("Power in milliWatts")
        self.ax.set_xlabel("Frequency (MHz)")
        self.ax.set_ylabel("Power (mW)")

        self.line, = self.ax.plot([], [], 'g-')

        self.ax.grid(True)
        self.fig.tight_layout()

    def update_plot(self, freqs, powers_mw):
        self.line.set_data(freqs / 1e6, powers_mw)

        self.ax.relim()
        self.ax.autoscale_view()

        self.draw()


class MachineApp(QWidget):
    """Main GUI application"""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Live RF Sweep and Analyzer")

        # --- Signals --- #
        self.comm = Communicate()
        self.comm.data_signal.connect(self.update_plot)
        self.comm.finished_signal.connect(self.on_finished)

        # --- User inputs --- #
        self.start_freq_input = QLineEdit("600e6")
        self.stop_freq_input = QLineEdit("1000e6")
        self.step_freq_input = QLineEdit("1e6")
        self.power_input = QLineEdit("0")
        self.dwell_input = QLineEdit("0.1")

        self.center_freq_input = QLineEdit()
        self.span_input = QLineEdit()

        # Auto populate centre & span for the initial defaults
        self.update_center_span_step()

        # Connect edits so any change in start/stop automatically refreshes
        self.start_freq_input.editingFinished.connect(
            self.update_center_span_step
        )
        self.stop_freq_input.editingFinished.connect(
            self.update_center_span_step
        )

        # --- Buttons --- #
        self.start_button = QPushButton("Start Live Sweep")
        self.start_button.clicked.connect(self.start_measurement)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_measurement)
        self.stop_button.setEnabled(False)

        # --- Layout --- #
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Signal Generator Settings"))

        layout.addWidget(QLabel("Start Frequency (Hz):"))
        layout.addWidget(self.start_freq_input)

        layout.addWidget(QLabel("Stop Frequency (Hz):"))
        layout.addWidget(self.stop_freq_input)

        layout.addWidget(QLabel("Step Frequency (Hz):"))
        layout.addWidget(self.step_freq_input)

        layout.addWidget(QLabel("Power (dBm):"))
        layout.addWidget(self.power_input)

        layout.addWidget(QLabel("Dwell Time (sec):"))
        layout.addWidget(self.dwell_input)

        layout.addWidget(QLabel("RF Spectrum Analyzer Settings"))

        layout.addWidget(QLabel("Center Frequency (Hz):"))
        layout.addWidget(self.center_freq_input)

        layout.addWidget(QLabel("Span (Hz):"))
        layout.addWidget(self.span_input)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)

        self.plot_canvas = LivePlotCanvas()
        layout.addWidget(self.plot_canvas)

        self.plot_canvas_mw = LivePlotCanvasMW()
        layout.addWidget(self.plot_canvas_mw)

        self.setLayout(layout)

        # --- Runtime vars --- #
        self._running = False
        self.rf_freqs = None
        self.csv_path = None

        # Keyword lists for auto detection
        self.signal_gen_keywords = [
            "SMC", "SMA", "SMB", "SGS", "SMU",
            "E8247", "E8257", "MXG", "EXG",
            "MG369", "SSG5000", "Siglent", "PSG", "AWG"
        ]

        self.spectrum_analyzer_keywords = [
            "FieldFox", "PSA", "ESA", "SSA3000",
            "XSA1000", "Signal Hound",
            "Spike", "Keysight", "Agilent"
        ]

    # ------------------------------------------------------------------ #
    # Helper methods for automatic centre/span & step size
    # ------------------------------------------------------------------ #

    def update_center_span_step(self):
        """Compute centre, span and an appropriate default step size."""

        try:
            start_freq = float(eval(self.start_freq_input.text()))
            stop_freq = float(eval(self.stop_freq_input.text()))
        except Exception:
            return

        span = abs(stop_freq - start_freq)
        center = (start_freq + stop_freq) / 2.0

        # Populate the fields
        self.center_freq_input.setText(f"{center}")
        self.span_input.setText(f"{span}")

        # Choose step resolution based on span
        if span >= 400e6:
            default_step = 1e6

        elif span >= 200e6:
            default_step = 0.5e6

        else:
            # Fallback: aim for ~400 points across the sweep
            default_step = span / 400 if span else 1e6

        self.step_freq_input.setText(f"{default_step}")

    # ------------------------------------------------------------------ #
    # Instrument handling & measurement logic
    # ------------------------------------------------------------------ #

    def detect_and_select_devices(self):

        self.rm = pyvisa.ResourceManager()
        resources = self.rm.list_resources()

        sig_gen_address = None
        rf_analyzer_address = None

        for addr in resources:

            try:
                inst = self.rm.open_resource(addr)

                idn = inst.query("*IDN?").strip()

                inst.close()

                print(f"Detected {addr}: {idn}")

                if any(keyword in idn for keyword in self.signal_gen_keywords):
                    sig_gen_address = addr

                elif any(
                    keyword in idn
                    for keyword in self.spectrum_analyzer_keywords
                ):
                    rf_analyzer_address = addr

            except Exception as e:
                print(f"Could not identify {addr}: {e}")

        if not sig_gen_address or not rf_analyzer_address:

            QMessageBox.critical(
                self,
                "Detection Failed",
                "Could not auto-detect both Signal Generator "
                "and RF Analyzer.\n"
                "Please ensure they are connected and powered on."
            )

            return None, None

        return sig_gen_address, rf_analyzer_address

    def start_measurement(self):

        try:
            # Recompute centre/span
            self.update_center_span_step()

            self.start_freq = float(eval(self.start_freq_input.text()))
            self.stop_freq = float(eval(self.stop_freq_input.text()))
            self.step_freq = float(eval(self.step_freq_input.text()))

            self.power_dbm = float(eval(self.power_input.text()))
            self.dwell_time = float(eval(self.dwell_input.text()))

            self.center_freq = float(
                eval(self.center_freq_input.text())
            )

            self.span = float(
                eval(self.span_input.text())
            )

        except Exception as e:

            QMessageBox.critical(
                self,
                "Input Error",
                f"Invalid input: {e}"
            )

            return

        desktop = Path.home() / "Desktop"

        default_file = desktop / "rf_live_data.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV File",
            str(default_file),
            "CSV Files (*.csv)"
        )

        if not path:
            return

        self.csv_path = path

        self._running = True

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        sig_address, rf_address = self.detect_and_select_devices()

        if not sig_address or not rf_address:

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            self._running = False

            return

        try:
            self.sig_gen = self.rm.open_resource(sig_address)
            self.rf_inst = self.rm.open_resource(rf_address)

        except Exception as e:

            QMessageBox.critical(
                self,
                "Connection Error",
                f"Failed to connect instruments: {e}"
            )

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

            self._running = False

            return

        self.sig_gen.write(f"POW {self.power_dbm} DBM")
        self.sig_gen.write("OUTP ON")

        self.rf_inst.write(f":FREQ:CENT {self.center_freq} Hz")
        self.rf_inst.write(f":FREQ:SPAN {self.span} Hz")

        self.rf_inst.write(":BAND:RES 1 MHz")
        self.rf_inst.write(":SWE:POIN 401")
        self.rf_inst.write(":TRAC1:TYPE MAXH")
        self.rf_inst.write(":INIT:CONT ON")

        start_rf = float(self.rf_inst.query(":FREQ:STAR?"))
        stop_rf = float(self.rf_inst.query(":FREQ:STOP?"))

        self.rf_freqs = np.linspace(start_rf, stop_rf, 401)

        self.last_powers = None

        self.sweep_thread = threading.Thread(
            target=self.signal_generator_sweep
        )

        self.rf_poll_thread = threading.Thread(
            target=self.rf_polling_loop
        )

        self.sweep_thread.start()
        self.rf_poll_thread.start()

    def signal_generator_sweep(self):

        for freq in np.arange(
            self.start_freq,
            self.stop_freq + self.step_freq,
            self.step_freq
        ):

            if not self._running:
                break

            self.sig_gen.write(f"FREQ {freq} HZ")

            time.sleep(self.dwell_time)

        self.sig_gen.write("OUTP OFF")

        self._running = False

    def rf_polling_loop(self):

        while self._running:

            try:
                powers = self.rf_inst.query_ascii_values(":TRAC:DATA?")

                if len(powers) == len(self.rf_freqs):

                    self.last_powers = powers

                    self.comm.data_signal.emit(
                        self.rf_freqs,
                        np.array(powers)
                    )

            except Exception as e:
                print("Error polling RF data:", e)

            time.sleep(0.5)

        if self.csv_path and self.last_powers is not None:

            with open(
                self.csv_path,
                mode='w',
                newline=''
            ) as file:

                writer = csv.writer(file)

                writer.writerow([
                    "Frequency (MHz)",
                    "Power (dBm)",
                    "Power (mW)"
                ])

                for f, p in zip(self.rf_freqs, self.last_powers):

                    writer.writerow([
                        f / 1e6,
                        p,
                        10 ** (p / 10)
                    ])

        try:
            self.sig_gen.close()
            self.rf_inst.close()
            self.rm.close()

        except:
            pass

        self.comm.finished_signal.emit()

    def update_plot(self, freqs, powers):

        self.plot_canvas.update_plot(freqs, powers)

        powers_mw = 10 ** (np.array(powers) / 10)

        self.plot_canvas_mw.update_plot(freqs, powers_mw)

    def on_finished(self):

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        QMessageBox.information(
            self,
            "Done",
            f"Measurement complete.\n"
            f"Data saved to:\n{self.csv_path}"
        )

    def stop_measurement(self):
        self._running = False


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = MachineApp()

    window.show()

    sys.exit(app.exec())
