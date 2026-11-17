"""Shared model controls for the native engineering panels."""
from __future__ import annotations

import os

from .agent.llm import DEFAULT_OLLAMA, DEFAULT_OPENAI, GEMMA4_MODEL, PRESETS, preset
from .qwen_cloud import QWEN_BACKEND, QWEN_MODEL, qwen_endpoint


def model_controls(QtCore, QtWidgets, prefix, *, discoverable=False, dhir=False):
    backend = QtWidgets.QComboBox()
    backend.setObjectName(prefix + "Backend")
    backend.addItems(["ollama", "openai", QWEN_BACKEND])
    backend.setItemData(2, "Qwen4-Max sends prompt and selected evidence to Alibaba Cloud.",
                        QtCore.Qt.ItemDataRole.ToolTipRole)
    env_model = os.environ.get("WENGOLD_LLM_MODEL") or "qwen2.5-coder:7b"
    known = preset(env_model)
    configured = os.environ.get("WENGOLD_LLM_BACKEND", "").strip().lower()
    # Local environment settings never select a cloud backend.
    initial = configured if configured in ("ollama", "openai") else (
        known.backend if known else "ollama")
    backend.setCurrentText(initial)
    defaults = {"ollama": DEFAULT_OLLAMA, "openai": DEFAULT_OPENAI,
                QWEN_BACKEND: qwen_endpoint()}
    endpoint = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_URL") or defaults[initial])
    endpoint.setObjectName(prefix + "Endpoint")
    if discoverable:
        model = QtWidgets.QComboBox()
        model.setEditable(True)
        model.addItem(env_model)
        set_model = model.setCurrentText
    else:
        model = QtWidgets.QLineEdit(env_model)
        set_model = model.setText
    model.setObjectName(prefix + "Model")

    local_choice = (initial, endpoint.text(), env_model)
    previous = initial

    def current_model():
        return model.currentText() if discoverable else model.text()

    def choose_backend(selected):
        nonlocal previous, local_choice
        if selected == QWEN_BACKEND:
            local_choice = (previous, endpoint.text(), current_model())
            endpoint.setText(defaults[selected])
            set_model(QWEN_MODEL)
        elif previous == QWEN_BACKEND:
            last_backend, last_endpoint, last_model = local_choice
            endpoint.setText(last_endpoint if selected == last_backend else defaults[selected])
            set_model(last_model)
        elif endpoint.text().strip() in ("", DEFAULT_OLLAMA, DEFAULT_OPENAI):
            endpoint.setText(defaults[selected])
        previous = selected

    backend.currentTextChanged.connect(choose_backend)
    buttons = QtWidgets.QHBoxLayout()

    def add_button(label, name, target, tag, tip):
        button = QtWidgets.QPushButton(label)
        button.setObjectName(prefix + name)
        button.setToolTip(tip)

        def select():
            switched_local = (backend.currentText() not in (target, QWEN_BACKEND)
                              and target != QWEN_BACKEND)
            backend.setCurrentText(target)
            if switched_local or not endpoint.text().strip():
                endpoint.setText(defaults[target])
            set_model(tag)

        button.clicked.connect(select)
        buttons.addWidget(button)

    if dhir:
        p = PRESETS["dhir-2b"]
        add_button("Use Dhīr 2B", "DhirPreset", p.backend, p.name, p.note + "\n" + p.serve)
    p = PRESETS[GEMMA4_MODEL]
    add_button("Use Gemma 4", "Gemma4Preset", p.backend, p.name, p.note + "\n" + p.serve)
    add_button("Use Qwen4-Max (cloud)", "Qwen4MaxPreset", QWEN_BACKEND, QWEN_MODEL,
               "Sends prompt and selected files or evidence to Alibaba Cloud. "
               "Requires explicit cloud opt-in and a Model Studio API key.")
    notice = QtWidgets.QLabel("Cloud mode · selected inputs go to Alibaba Cloud")
    notice.setObjectName(prefix + "CloudNotice")
    notice.setHidden(True)
    backend.currentTextChanged.connect(lambda selected: notice.setVisible(selected == QWEN_BACKEND))
    buttons.addWidget(notice)
    buttons.addStretch(1)
    return backend, endpoint, model, buttons
