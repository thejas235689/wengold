"""Optional Matplotlib-backed Bloch sphere, Q-sphere and measurement inspector."""
from __future__ import annotations


def build_state_visualizer(QtWidgets):
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    from quantum.visualization.state import bloch_vectors, qsphere_points

    class StateVisualizer(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._bloch = Figure(figsize=(5, 4), tight_layout=True)
            self._qsphere = Figure(figsize=(5, 4), tight_layout=True)
            self._measurements = Figure(figsize=(5, 4), tight_layout=True)
            self._bloch_canvas = FigureCanvasQTAgg(self._bloch)
            self._qsphere_canvas = FigureCanvasQTAgg(self._qsphere)
            self._measurement_canvas = FigureCanvasQTAgg(self._measurements)
            self._summary = QtWidgets.QLabel("Run a circuit to inspect its quantum state.")
            self._summary.setWordWrap(True)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self._bloch_canvas, "Bloch spheres")
            tabs.addTab(self._qsphere_canvas, "Q-sphere")
            tabs.addTab(self._measurement_canvas, "Measurements")
            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(self._summary)
            layout.addWidget(tabs, 1)
            self.setMinimumWidth(380)
            self._draw_empty()

        def _draw_empty(self):
            ax = self._bloch.add_subplot(111, projection="3d")
            self._draw_sphere(ax)
            ax.set_title("Single-qubit reduced states")
            self._bloch_canvas.draw()
            ax2 = self._qsphere.add_subplot(111, projection="3d")
            self._draw_sphere(ax2)
            ax2.set_title("Basis states on Q-sphere")
            self._qsphere_canvas.draw()
            self._measurements.add_subplot(111).set_title("No measurement counts yet")
            self._measurement_canvas.draw()

        @staticmethod
        def _draw_sphere(ax):
            import numpy as np
            u = np.linspace(0, 2 * np.pi, 40)
            v = np.linspace(0, np.pi, 24)
            x = np.outer(np.cos(u), np.sin(v))
            y = np.outer(np.sin(u), np.sin(v))
            z = np.outer(np.ones_like(u), np.cos(v))
            ax.plot_wireframe(x, y, z, rstride=4, cstride=4, alpha=0.15, linewidth=0.5)
            ax.set(xlim=(-1.1, 1.1), ylim=(-1.1, 1.1), zlim=(-1.1, 1.1))
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
            ax.set_zlabel("Z")
            ax.set_box_aspect((1, 1, 1))

        def set_statevector(self, statevector):
            vectors = bloch_vectors(statevector)
            points = qsphere_points(statevector)
            self._bloch.clear()
            ax = self._bloch.add_subplot(111, projection="3d")
            self._draw_sphere(ax)
            for vector in vectors:
                ax.quiver(0, 0, 0, vector.x, vector.y, vector.z, arrow_length_ratio=0.12)
                ax.text(vector.x, vector.y, vector.z, f" q{vector.qubit}")
            ax.set_title("Reduced-state Bloch vectors")
            self._bloch_canvas.draw()

            self._qsphere.clear()
            qax = self._qsphere.add_subplot(111, projection="3d")
            self._draw_sphere(qax)
            if points:
                import math
                xs, ys, zs, sizes, colors = [], [], [], [], []
                for point in points:
                    xs.append(math.sin(point.theta) * math.cos(point.phi))
                    ys.append(math.sin(point.theta) * math.sin(point.phi))
                    zs.append(math.cos(point.theta))
                    sizes.append(40 + 700 * point.probability)
                    colors.append(point.phase)
                qax.scatter(xs, ys, zs, s=sizes, c=colors, cmap="twilight",
                            vmin=-math.pi, vmax=math.pi, depthshade=True)
                for point, x, y, z in zip(points, xs, ys, zs):
                    qax.text(x, y, z, f" {point.basis}")
            qax.set_title("Q-sphere: Hamming-weight latitude / relative phase longitude")
            self._qsphere_canvas.draw()
            self._summary.setText(
                f"{len(vectors)} qubits · {len(points)} displayed basis states · "
                "Q-sphere displays at most 2,048 highest-probability states; phase is relative to the largest amplitude."
            )

        def set_measurements(self, counts):
            self._measurements.clear()
            ax = self._measurements.add_subplot(111)
            keys = list(counts)
            values = [int(counts[key]) for key in keys]
            ax.bar(keys, values)
            ax.set_xlabel("Classical outcome c[n-1]...c[0]")
            ax.set_ylabel("Shots")
            ax.set_title("Measurement histogram")
            ax.tick_params(axis="x", rotation=45)
            self._measurements.tight_layout()
            self._measurement_canvas.draw()
            self._summary.setText(
                f"{sum(values)} shots · {len(keys)} observed outcomes · "
                "measurement data shown without inferring a post-measurement statevector."
            )

    return StateVisualizer()
