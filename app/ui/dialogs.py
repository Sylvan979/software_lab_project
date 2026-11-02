"""可复用的小型模态对话框。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui.base import ModalDialog


class ChoiceDialog(ModalDialog):
    """从固定选项中单选；返回值或 None（取消）。"""

    def __init__(self, parent, title: str, options: list[str], prompt: str = "") -> None:
        super().__init__(parent, title)
        self.value = tk.StringVar(value=options[0] if options else "")
        ttk.Label(self.body, text=prompt or title, style="Muted.TLabel").pack(anchor="w")
        ttk.Combobox(
            self.body,
            textvariable=self.value,
            values=options,
            state="readonly",
            width=26,
        ).pack(fill="x", pady=10)
        ttk.Button(
            self.body, text="确定", style="Accent.TButton", command=self._submit
        ).pack(anchor="e")

    def _submit(self) -> None:
        if not self.value.get():
            return
        self.result = self.value.get()
        self.destroy()


class TextDialog(ModalDialog):
    """单行文本输入（可带默认值）；空字符串是合法结果。"""

    def __init__(self, parent, title: str, prompt: str, initial: str = "") -> None:
        super().__init__(parent, title)
        self.value = tk.StringVar(value=initial)
        ttk.Label(self.body, text=prompt, style="Muted.TLabel").pack(anchor="w")
        entry = ttk.Entry(self.body, textvariable=self.value, width=34)
        entry.pack(fill="x", pady=10)
        entry.bind("<Return>", lambda _event: self._submit())
        entry.focus_set()
        ttk.Button(
            self.body, text="确定", style="Accent.TButton", command=self._submit
        ).pack(anchor="e")

    def _submit(self) -> None:
        self.result = self.value.get().strip()
        self.destroy()
