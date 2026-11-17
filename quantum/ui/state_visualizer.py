"""Optional Matplotlib-backed Bloch sphere and Q-sphere inspector."""
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
            self._bloch_canvas = FigureCanvasQTAgg(self._bloch)
            self._qsphere_canvas = FigureCanvasQTAgg(self._qsphere)
            self._summary = QtWidgets.QLabel("Run a statevector simulation to inspect the state.")
            self._summary.setWordWrap(True)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self._bloch_canvas, "Bloch spheres")
            tabs.addTab(self._qsphere_canvas, "Q-sphere")
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
                xs, ys, zs, sizes, colors = [], [], [], [], []
                for point in points:
                    xs.append(__import__("math").sin(point.theta) * __import__("math").cos(point.phi))
                    ys.append(__import__("math").sin(point.theta) * __import__("math").sin(point.phi))
                    zs.append(__import__("math").cos(point.theta))
                    sizes.append(40 + 700 * point.probability)
                    colors.append(point.phase)
                qax.scatter(xs, ys, zs, s=sizes, c=colors, cmap="twilight", vmin=-3.14159, vmax=3.14159, depthshade=True)
                for point, x, y, z in zip(points, xs, ys, zs):
                    qax.text(x, y, z, f" {point.basis}")
            qax.set_title("Q-sphere: Hamming-weight latitude / relative phase longitude")
            self._qsphere_canvas.draw()
            self._summary.setText(
                f"{len(vectors)} qubits · {len(points)} populated basis states · "
                "Bloch vectors show reduced states; Q-sphere phase is relative to the largest amplitude."
            )

    return StateVisualizer()
