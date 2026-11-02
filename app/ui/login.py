"""登录与注册界面。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.domain.enums import UserRole
from app.exceptions import DomainError
from app.ui.widgets import add_field

DEMO_DATA = (
    ("顾客", "13800000001"),
    ("商家·川味小厨", "13900000001"),
    ("商家·轻食日记", "13900000002"),
    ("骑手", "13700000001"),
    ("管理员", "13600000001"),
)


class LoginView(ttk.Frame):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master)
        self.app = app
        self.ctx = app.ctx
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        card = ttk.Frame(self, style="Card.TFrame", padding=(42, 34))
        card.grid(row=0, column=0)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="城市外卖点餐与配送平台", style="H1.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text="软件工程实验三 · 可运行原型　｜　四端合一桌面应用",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        notebook = ttk.Notebook(card)
        notebook.grid(row=2, column=0, sticky="ew")
        self._build_login_tab(notebook)
        self._build_register_tab(notebook)

        ttk.Label(
            card,
            text=f"演示验证码：{self.ctx.settings.demo_code}　｜　数据保存在 data/platform.json",
            style="CardMuted.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(16, 0))

        self._demo_frame = ttk.Frame(card, style="Card.TFrame")
        self._demo_frame.grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(
            self._demo_frame, text="一键填入演示账号：", style="CardMuted.TLabel"
        ).pack(side="left")
        for label, phone in DEMO_DATA:
            ttk.Button(
                self._demo_frame,
                text=label,
                command=lambda p=phone: self._fill(p),
            ).pack(side="left", padx=3)

    # ------------------------------------------------------------------ #
    def _build_login_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=18)
        notebook.add(tab, text="登录")

        self.login_phone = tk.StringVar(value="13800000001")
        self.login_code = tk.StringVar(value=self.ctx.settings.demo_code)
        add_field(tab, 0, 0, "手机号", self.login_phone, width=24)
        entry = add_field(tab, 1, 0, "验证码", self.login_code, width=24)
        entry.bind("<Return>", lambda _event: self._login())

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(actions, text="登录", style="Accent.TButton", command=self._login).pack(
            side="left"
        )
        ttk.Button(
            actions, text="获取验证码", command=self._request_code
        ).pack(side="left", padx=8)

    def _build_register_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=18)
        notebook.add(tab, text="注册")

        self.reg_role = tk.StringVar(value=UserRole.CUSTOMER.label)
        self.reg_phone = tk.StringVar()
        self.reg_nickname = tk.StringVar()
        self.reg_code = tk.StringVar(value=self.ctx.settings.demo_code)

        ttk.Label(tab, text="角色", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=3
        )
        ttk.Combobox(
            tab,
            textvariable=self.reg_role,
            values=[UserRole.CUSTOMER.label, UserRole.MERCHANT.label, UserRole.RIDER.label],
            state="readonly",
            width=21,
        ).grid(row=0, column=1, sticky="w", pady=3)
        add_field(tab, 1, 0, "手机号", self.reg_phone, width=24)
        add_field(tab, 2, 0, "昵称", self.reg_nickname, width=24)
        add_field(tab, 3, 0, "验证码", self.reg_code, width=24)

        ttk.Button(
            tab, text="注册并登录", style="Accent.TButton", command=self._do_register
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 0))

    # ------------------------------------------------------------------ #
    def _fill(self, phone: str) -> None:
        self.login_phone.set(phone)
        self.login_code.set(self.ctx.settings.demo_code)

    def _request_code(self) -> None:
        try:
            code = self.ctx.auth.request_code(self.login_phone.get())
            messagebox.showinfo(
                "验证码", f"演示环境验证码为：{code}", parent=self
            )
        except DomainError as exc:
            messagebox.showerror("获取失败", str(exc), parent=self)

    def _login(self) -> None:
        try:
            session = self.ctx.auth.login(
                self.login_phone.get(), self.login_code.get()
            )
        except DomainError as exc:
            messagebox.showerror("登录失败", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            messagebox.showerror("系统错误", str(exc), parent=self)
            return
        self.app.on_login(session)

    def _do_register(self) -> None:
        role = {
            UserRole.CUSTOMER.label: UserRole.CUSTOMER,
            UserRole.MERCHANT.label: UserRole.MERCHANT,
            UserRole.RIDER.label: UserRole.RIDER,
        }[self.reg_role.get()]
        try:
            self.ctx.auth.register(
                self.reg_phone.get(),
                self.reg_nickname.get(),
                role,
                self.reg_code.get(),
            )
            session = self.ctx.auth.login(self.reg_phone.get(), self.reg_code.get())
        except DomainError as exc:
            messagebox.showerror("注册失败", str(exc), parent=self)
            return
        messagebox.showinfo("注册成功", f"已创建{role.label}账号并登录", parent=self)
        self.app.on_login(session)
