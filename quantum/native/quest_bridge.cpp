#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <quest.h>

#include <cmath>
#include <mutex>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {
std::mutex quest_mutex;

struct Environment {
    Environment() { initQuESTEnv(); }
    ~Environment() { finalizeQuESTEnv(); }
    Environment(const Environment&) = delete;
    Environment& operator=(const Environment&) = delete;
};

struct Register {
    Qureg value;
    explicit Register(int n) : value(createQureg(n)) {}
    ~Register() { destroyQureg(value); }
    Register(const Register&) = delete;
    Register& operator=(const Register&) = delete;
};

using Gate = std::tuple<std::string, std::vector<int>, std::vector<int>, double>;

void apply_gate(Qureg q, const Gate& item) {
    const auto& gate = std::get<0>(item);
    const auto& targets = std::get<1>(item);
    const auto& controls = std::get<2>(item);
    const double angle = std::get<3>(item);
    const int a = targets.empty() ? -1 : targets[0];
    const int b = targets.size() < 2 ? -1 : targets[1];

    if (gate == "I" || gate == "BARRIER") return;
    if (gate == "H") applyHadamard(q, a);
    else if (gate == "X") applyPauliX(q, a);
    else if (gate == "Y") applyPauliY(q, a);
    else if (gate == "Z") applyPauliZ(q, a);
    else if (gate == "S") applyPhaseShift(q, a, M_PI / 2.0);
    else if (gate == "SDG") applyPhaseShift(q, a, -M_PI / 2.0);
    else if (gate == "T") applyPhaseShift(q, a, M_PI / 4.0);
    else if (gate == "TDG") applyPhaseShift(q, a, -M_PI / 4.0);
    else if (gate == "RX") applyRotateX(q, a, angle);
    else if (gate == "RY") applyRotateY(q, a, angle);
    else if (gate == "RZ") applyRotateZ(q, a, angle);
    else if (gate == "CNOT" || gate == "CX") applyControlledPauliX(q, controls.at(0), a);
    else if (gate == "CZ") applyControlledPauliZ(q, a, b);
    else if (gate == "SWAP") applySwap(q, a, b);
    else if (gate == "CCX" || gate == "TOFFOLI") {
        auto ctrls = controls;
        applyMultiControlledPauliX(q, ctrls.data(), static_cast<int>(ctrls.size()), a);
    } else if (gate == "CSWAP") {
        applyControlledSwap(q, controls.at(0), a, b);
    } else {
        throw std::invalid_argument("QuEST bridge does not support gate: " + gate);
    }
}
} // namespace

std::vector<std::pair<double, double>> run_statevector(int num_qubits, const std::vector<Gate>& gates) {
    if (num_qubits < 1 || num_qubits > 30)
        throw std::invalid_argument("QuEST bridge currently accepts 1..30 qubits per request");
    std::lock_guard<std::mutex> lock(quest_mutex);
    Environment env;
    Register reg(num_qubits);
    for (const auto& gate : gates) apply_gate(reg.value, gate);

    const long long count = getNumAmps(reg.value);
    std::vector<std::pair<double, double>> state;
    state.reserve(static_cast<size_t>(count));
    for (long long i = 0; i < count; ++i)
        state.emplace_back(static_cast<double>(getRealAmp(reg.value, i)),
                           static_cast<double>(getImagAmp(reg.value, i)));
    return state;
}

PYBIND11_MODULE(_quest_bridge, m) {
    m.doc() = "WENGOLD QuEST v4 native statevector bridge";
    m.def("run_statevector", &run_statevector, py::arg("num_qubits"), py::arg("gates"));
}
