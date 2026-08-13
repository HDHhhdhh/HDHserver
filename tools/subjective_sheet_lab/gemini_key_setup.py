from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Final

KEY_NAME: Final[str] = "GEMINI_API_KEY"
SERVER_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SERVER_ENV_PATH: Final[Path] = SERVER_ROOT / ".env"
KEY_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*GEMINI_API_KEY\s*=")


class MissingKeyError(Exception):
    def __init__(self) -> None:
        super().__init__("Gemini API key is empty.")


def main() -> int:
    parse_args()
    run_gui(SERVER_ENV_PATH)
    return 0


def parse_args() -> None:
    parser = argparse.ArgumentParser(description="Save GEMINI_API_KEY to the local C:\\server\\.env file.")
    parser.parse_args()


def run_gui(env_path: Path) -> None:
    configure_tcl_tk_paths()
    root = tk.Tk()
    root.title("Gemini API Key Setup")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    api_key = tk.StringVar()
    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frame, text="Gemini API Key").grid(row=0, column=0, columnspan=2, sticky="w")
    entry = ttk.Entry(frame, textvariable=api_key, width=56, show="*")
    entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 12))
    entry.focus_set()

    status = ttk.Label(frame, text="")
    status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))

    def save_and_close() -> None:
        try:
            write_env_key(env_path, api_key.get())
        except MissingKeyError:
            status.config(text="API key is empty.")
            entry.focus_set()
            return
        api_key.set("")
        entry.delete(0, tk.END)
        messagebox.showinfo("Saved", f"{KEY_NAME} saved to {env_path}")
        root.destroy()

    ttk.Button(frame, text="Save", command=save_and_close).grid(row=3, column=0, sticky="e", padx=(0, 8))
    ttk.Button(frame, text="Cancel", command=root.destroy).grid(row=3, column=1, sticky="w")

    root.bind("<Return>", lambda _event: save_and_close())
    root.bind("<Escape>", lambda _event: root.destroy())
    root.update_idletasks()
    center_window(root)
    root.lift()
    root.focus_force()
    root.after(2000, lambda: root.attributes("-topmost", False))
    root.mainloop()


def configure_tcl_tk_paths() -> None:
    python_root = Path(sys.base_prefix)
    tcl_path = python_root / "tcl" / "tcl8.6"
    tk_path = python_root / "tcl" / "tk8.6"
    bridge_tcl_path, bridge_tk_path = ensure_ascii_tk_runtime(python_root, tcl_path, tk_path)
    if bridge_tcl_path is not None and bridge_tk_path is not None:
        os.environ.setdefault("TCL_LIBRARY", str(bridge_tcl_path))
        os.environ.setdefault("TK_LIBRARY", str(bridge_tk_path))
        return

    if tcl_path.is_dir():
        os.environ.setdefault("TCL_LIBRARY", short_windows_path(tcl_path))
    if tk_path.is_dir():
        os.environ.setdefault("TK_LIBRARY", short_windows_path(tk_path))


def ensure_ascii_tk_runtime(python_root: Path, tcl_path: Path, tk_path: Path) -> tuple[Path | None, Path | None]:
    if not tcl_path.is_dir() or not tk_path.is_dir():
        return None, None

    bridge_root = SERVER_ROOT / ".codex_tk_runtime" / python_root.name / "tcl"
    bridge_tcl_path = bridge_root / "tcl8.6"
    bridge_tk_path = bridge_root / "tk8.6"
    try:
        copy_runtime_dir(tcl_path, bridge_tcl_path, "init.tcl")
        copy_runtime_dir(tk_path, bridge_tk_path, "tk.tcl")
    except OSError:
        return None, None
    return bridge_tcl_path, bridge_tk_path


def copy_runtime_dir(source: Path, destination: Path, required_file: str) -> None:
    if (destination / required_file).is_file():
        return
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def short_windows_path(path: Path) -> str:
    text = str(path)
    if os.name != "nt":
        return text

    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer))
    if result == 0 or result >= len(buffer):
        return text
    return buffer.value


def center_window(root: tk.Tk) -> None:
    width = root.winfo_reqwidth()
    height = root.winfo_reqheight()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"+{x}+{y}")


def write_env_key(env_path: Path, raw_key: str) -> None:
    key = raw_key.strip()
    if not key:
        raise MissingKeyError()

    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = read_env_lines(env_path)
    updated = replace_key_line(lines, key)
    env_path.write_text("".join(updated), encoding="utf-8")


def read_env_lines(env_path: Path) -> list[str]:
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)


def replace_key_line(lines: list[str], key: str) -> list[str]:
    replacement = f"{KEY_NAME}={key}\n"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if KEY_LINE_RE.match(line):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)

    if replaced:
        return updated

    if updated and not updated[-1].endswith(("\n", "\r")):
        updated[-1] = f"{updated[-1]}\n"
    updated.append(replacement)
    return updated


if __name__ == "__main__":
    raise SystemExit(main())
