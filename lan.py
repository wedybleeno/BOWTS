# -*- coding: utf-8 -*-
import ctypes
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def interfaces_up() -> bool:
    # Используем powershell, чтобы получить список включённых адаптеров
    cmd = [
        "powershell",
        "-Command",
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return bool(proc.stdout.strip())

def disable_all():
    cmd = [
        "powershell",
        "-Command",
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Disable-NetAdapter -Confirm:$false"
    ]
    subprocess.run(cmd, capture_output=True, text=True)

def enable_all():
    cmd = [
        "powershell",
        "-Command",
        "Get-NetAdapter | Where-Object {$_.Status -ne 'Up'} | Enable-NetAdapter -Confirm:$false"
    ]
    subprocess.run(cmd, capture_output=True, text=True)

def toggle():
    try:
        if interfaces_up():
            disable_all()
            btn.config(text="Включить интернет")
        else:
            enable_all()
            btn.config(text="Выключить интернет")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось переключить адаптеры:\n{e}")

if not is_admin():
    messagebox.showerror(
        "Ошибка прав",
        "Запустите программу с правами администратора!"
    )
    sys.exit(1)

root = tk.Tk()
root.title("Toggle Internet")
root.geometry("320x150")
root.resizable(False, False)

btn = tk.Button(
    root,
    text="Проверка...",
    font=("Segoe UI", 14, "bold"),
    command=toggle,
    relief=tk.RAISED,
)
btn.pack(expand=True, fill=tk.BOTH, padx=24, pady=24)

btn.config(text="Выключить интернет" if interfaces_up() else "Включить интернет")

root.mainloop()
