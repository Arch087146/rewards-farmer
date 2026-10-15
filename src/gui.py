"""A window onto the pieces that already exist.

The farmer is driven from the command line: `main.py` works through the
accounts named in `.env`, and `init-config.py` writes that file and can sign a
profile in. Nothing here adds a capability the command line does not already
have. It is the same three things with buttons instead of prompts:

    Run       start `main.py` and watch its log while it works
    Accounts  add, remove and sign in to the profile directories
    Settings  read and write the same values `init-config.py` asks about

Tkinter ships with Python, so the window costs no new dependency. Start it
with `python src/gui.py`, or with `pythonw src/gui.py` on Windows to do
without the console window.
"""

import logging
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field as dataclass_field
from tkinter import filedialog, messagebox, ttk

import dotenv

import accounts
import browser
import log_utils
from constants import DEFAULT_ROOT_DATA_DIR, DOTENV_PATH, REPO_ROOT

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(SRC_DIR, "main.py")

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

# Two palettes with the same keys. apply_palette() copies one over the module
# names below, so everything built afterwards uses it, and the caller rebuilds
# the widgets already on screen. The chosen name is remembered in .env under
# THEME_ENV_KEY, which the bot itself never reads - it is a window preference
# only, kept with the rest of the window's state so there is no second file.
LIGHT_PALETTE = {
	"APP_BG": "#f4f5f7",
	"CARD_BG": "#ffffff",
	"HEADER_BG": "#ffffff",
	"BORDER": "#e2e4e8",
	"ACCENT": "#0f6cbd",
	"ACCENT_ACTIVE": "#0b5a9e",
	"ACCENT_DISABLED": "#a9c8e6",
	"TEXT": "#1f1f1f",
	"MUTED": "#61656b",
	"DANGER": "#c42b1c",
	"SUCCESS": "#107c10",
	"IDLE": "#8a8f98",
	"SIDEBAR_BG": "#ffffff",
	"NAV_HOVER": "#f2f4f7",
	"NAV_SELECTED": "#e8f1fb",
	"TRACK_OFF": "#c9ccd1",
	"BTN_HOVER": "#eceef1",
	"GHOST_HOVER": "#eef4fb",
	"INPUT_BG": "#ffffff",
	"CONSOLE_BG": "#ffffff",
	"CONSOLE_FG": "#24292f",
	"CONSOLE_ERROR": "#b3261e",
	"CONSOLE_WARNING": "#8a6100",
	"CONSOLE_SUCCESS": "#107c10",
	"CONSOLE_MUTED": "#6a6f76",
}

DARK_PALETTE = {
	"APP_BG": "#1b1d21",
	"CARD_BG": "#25272b",
	"HEADER_BG": "#202225",
	"BORDER": "#3a3d42",
	"ACCENT": "#4c9be8",
	"ACCENT_ACTIVE": "#3d84cc",
	"ACCENT_DISABLED": "#39516b",
	"TEXT": "#e8eaed",
	"MUTED": "#9aa0a6",
	"DANGER": "#f2857c",
	"SUCCESS": "#7bd88f",
	"IDLE": "#8a8f98",
	"SIDEBAR_BG": "#202225",
	"NAV_HOVER": "#2a2d31",
	"NAV_SELECTED": "#2f3a46",
	"TRACK_OFF": "#54585e",
	"BTN_HOVER": "#32353a",
	"GHOST_HOVER": "#2f3a46",
	"INPUT_BG": "#2b2d31",
	"CONSOLE_BG": "#141517",
	"CONSOLE_FG": "#d7dae0",
	"CONSOLE_ERROR": "#ff9c9c",
	"CONSOLE_WARNING": "#ffd27d",
	"CONSOLE_SUCCESS": "#8ce99a",
	"CONSOLE_MUTED": "#8a8f98",
}

PALETTES = {"Light": LIGHT_PALETTE, "Dark": DARK_PALETTE}

THEME_ENV_KEY = "GUI_THEME"

# Accounts the window leaves out of a run, by name. The bot never reads this;
# the window turns it into the REWARDS_ACCOUNTS it hands the run, so the list
# in .env stays the full set and "exclude" is a window-side view of it.
EXCLUDE_ENV_KEY = "GUI_EXCLUDED_ACCOUNTS"

# The names the rest of this module reads. apply_palette() rebinds them, so
# every widget built after a switch picks the new colours up.
APP_BG = LIGHT_PALETTE["APP_BG"]
CARD_BG = LIGHT_PALETTE["CARD_BG"]
HEADER_BG = LIGHT_PALETTE["HEADER_BG"]
BORDER = LIGHT_PALETTE["BORDER"]
ACCENT = LIGHT_PALETTE["ACCENT"]
ACCENT_ACTIVE = LIGHT_PALETTE["ACCENT_ACTIVE"]
ACCENT_DISABLED = LIGHT_PALETTE["ACCENT_DISABLED"]
TEXT = LIGHT_PALETTE["TEXT"]
MUTED = LIGHT_PALETTE["MUTED"]
DANGER = LIGHT_PALETTE["DANGER"]
SUCCESS = LIGHT_PALETTE["SUCCESS"]
IDLE = LIGHT_PALETTE["IDLE"]
SIDEBAR_BG = LIGHT_PALETTE["SIDEBAR_BG"]
NAV_HOVER = LIGHT_PALETTE["NAV_HOVER"]
NAV_SELECTED = LIGHT_PALETTE["NAV_SELECTED"]
TRACK_OFF = LIGHT_PALETTE["TRACK_OFF"]
BTN_HOVER = LIGHT_PALETTE["BTN_HOVER"]
GHOST_HOVER = LIGHT_PALETTE["GHOST_HOVER"]
INPUT_BG = LIGHT_PALETTE["INPUT_BG"]
CONSOLE_BG = LIGHT_PALETTE["CONSOLE_BG"]
CONSOLE_FG = LIGHT_PALETTE["CONSOLE_FG"]
CONSOLE_ERROR = LIGHT_PALETTE["CONSOLE_ERROR"]
CONSOLE_WARNING = LIGHT_PALETTE["CONSOLE_WARNING"]
CONSOLE_SUCCESS = LIGHT_PALETTE["CONSOLE_SUCCESS"]
CONSOLE_MUTED = LIGHT_PALETTE["CONSOLE_MUTED"]


def apply_palette(name: str) -> str:
	"""Rebind the module colour names to one palette.

	Returns the name actually used, so an unknown or missing value lands on
	Light rather than leaving the colours unset.
	"""

	chosen = name if name in PALETTES else "Light"
	globals().update(PALETTES[chosen])

	return chosen


def detect_system_theme() -> str:
	"""Light or Dark, following Windows when it can be read, else Light."""

	try:
		import winreg

		with winreg.OpenKey(
			winreg.HKEY_CURRENT_USER,
			r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
		) as key:
			value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")

		return "Light" if value else "Dark"
	except Exception:
		return "Light"

BASE_FONT = ("Segoe UI", 10)
BOLD_FONT = ("Segoe UI", 10, "bold")
TITLE_FONT = ("Segoe UI", 15, "bold")
SECTION_FONT = ("Segoe UI", 11, "bold")
MONO_FONT = ("Consolas", 9)

# How many console lines to keep before dropping the oldest. The log of a run
# is useful, an unbounded one is a memory leak that also gets slower to draw.
MAX_CONSOLE_LINES = 5000


def _env_value(value: str) -> str:
	"""Format a value the way `.env` can hold it unchanged.

	Unquoted is the point: a Windows path in double quotes has its `\\n` and
	`\\t` read as escapes, which is how a valid path silently becomes a broken
	one. Quote only what would otherwise not survive the trip, and escape the
	backslashes when a quote is forced.
	"""
	value = str(value)

	needs_quotes = (
		value != value.strip()
		or "\n" in value
		or '"' in value
		or value.startswith("'")
		or re.search(r"(^|\s)#", value) is not None
	)

	if not needs_quotes:
		return value

	escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

	return f'"{escaped}"'


class EnvFile:
	"""The `.env` on disk, read and updated line by line.

	Only the keys handed to `update` are touched. Comments, blank lines and
	keys this window does not know about stay exactly where they were, so the
	file stays hand-editable the way the README promises.
	"""

	KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")

	def __init__(self, path: str):
		self.path = path

	def values(self) -> dict[str, str]:
		return {
			key: value
			for key, value in dotenv.dotenv_values(self.path).items()
			if value is not None
		}

	def get(self, key: str, default: str = "") -> str:
		return self.values().get(key, default)

	def update(self, updates: dict[str, str]) -> None:
		"""Write the given keys, remove the blank ones, leave the rest alone."""
		lines: list[str] = []

		if os.path.isfile(self.path):
			with open(self.path, "r", encoding="utf-8") as handle:
				lines = handle.read().splitlines()

		remaining = dict(updates)
		written: list[str] = []

		for line in lines:
			match = self.KEY.match(line)

			if not match or match.group(1) not in remaining:
				written.append(line)
				continue

			key = match.group(1)
			value = remaining.pop(key)

			# An empty field means "unset". Dropping the line is what lets a
			# cleared setting actually clear, rather than leaving the old
			# value sitting there for the code's fallback to never reach.
			if value != "":
				written.append(f"{key}={_env_value(value)}")

		for key, value in remaining.items():
			if value != "":
				written.append(f"{key}={_env_value(value)}")

		text = "\n".join(written)

		if text:
			text += "\n"

		with open(self.path, "w", encoding="utf-8") as handle:
			handle.write(text)


@dataclass(frozen=True)
class Field:
	"""One editable `.env` value, and how it wants to be shown."""

	key: str
	label: str
	kind: str = "text"
	choices: tuple = ()
	default: str = ""
	browse: str = ""


@dataclass(frozen=True)
class Section:
	title: str
	fields: tuple = dataclass_field(default_factory=tuple)


SETTINGS: tuple = (
	Section("Search", (
		Field("QUERY_SOURCE", "Search backend", "choice", ("trends", "llm"), "llm"),
	)),
	Section("LLM (used when the search backend is llm)", (
		Field("LLM_PROVIDER", "Provider", "choice", ("openrouter", "local"), "local"),
		Field("OPENROUTER_API_KEY", "OpenRouter API key"),
		Field("OPENROUTER_MODEL", "OpenRouter model", default="openrouter/free"),
		Field("OPENROUTER_BASE_URL", "OpenRouter base URL", default="https://openrouter.ai/api/v1"),
		Field("LOCAL_LLM_BASE_URL", "Local base URL", default="http://localhost:11434/v1"),
		Field("LOCAL_LLM_MODEL", "Local model", default="gemma4:cloud"),
		Field("LOCAL_LLM_API_KEY", "Local API key"),
		Field("LLM_REQUEST_TIMEOUT_SECONDS", "Request timeout (seconds)", "int", default="60"),
	)),
	Section("Browser", (
		Field("REWARDS_HEADLESS", "Headless", "bool", default="false"),
		Field("EDGE_BINARY", "Edge executable", browse="file"),
		Field("MSEDGEDRIVER_PATH", "msedgedriver executable", browse="file"),
	)),
	Section("Accounts", (
		Field("USER_DATA_DIR", "Profile data directory", browse="dir", default=DEFAULT_ROOT_DATA_DIR),
	)),
	Section("Logging", (
		Field("REWARDS_FARMER_LOG_LEVEL", "Log level", "choice",
			("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), "INFO"),
		Field("REWARDS_DRIVER_LOG", "Driver log file", browse="file"),
		Field("REWARDS_FARMER_LOG_FILE", "Farmer log file", browse="file"),
	)),
	Section("Windows virtual desktop", (
		Field("USE_VIRTUAL_DESKTOP", "Run on a separate virtual desktop", "bool", default="false"),
		Field("SWITCH_BACK_TO_MAIN_DESKTOP", "Switch back after launching", "bool", default="true"),
		Field("SWITCH_BACK_DELAY_SECONDS", "Switch-back delay (seconds)", "float", default="1.5"),
		Field("CLEANUP_VIRTUAL_DESKTOP", "Close the worker desktop when done", "bool", default="true"),
	)),
)

ALL_FIELDS: tuple = tuple(field for section in SETTINGS for field in section.fields)


def _to_bool(value: str) -> bool:
	return str(value).strip().lower() in ("1", "true", "yes", "on")


def split_account_names(text: str) -> list[str]:
	"""Profile names from free text, split on commas, semicolons and lines.

	So a copied list - one per line, or comma separated - pastes straight in.
	"""

	return [
		part
		for part in (chunk.strip() for chunk in re.split(r"[,;\s]+", text or ""))
		if part
	]


def partition_accounts(names: list[str], excluded_raw: str) -> tuple[list[str], list[str]]:
	"""Split configured names into (farming, excluded) using the exclude list.

	Everything farms unless it appears in the exclude list. An entry in that
	list which is no longer configured is ignored, so a leftover name can never
	hide an account that is actually present.
	"""

	excluded = {name.lower() for name in split_account_names(excluded_raw)}

	farming = [name for name in names if name.lower() not in excluded]
	skipped = [name for name in names if name.lower() in excluded]

	return farming, skipped


def _signed_in_profiles(profile_dir: str) -> dict:
	"""The user-data-dir's `Local State` info_cache, or an empty dict.

	Keyed by browser profile directory ("Default", "Profile 1", ...). Each entry
	carries the `user_name` signed into that browser profile, which is what the
	bot's `--profile-directory` actually opens.
	"""

	try:
		with open(os.path.join(profile_dir, "Local State"), encoding="utf-8") as handle:
			return json.load(handle).get("profile", {}).get("info_cache", {}) or {}
	except (OSError, ValueError):
		return {}


def _recorded_accounts(profile_dir: str) -> list:
	"""The opened profile's `account_info`, or an empty list.

	Every account ever used on the profile is listed here, in no particular
	order, so the first entry is not necessarily the account signed in now.
	"""

	try:
		with open(os.path.join(profile_dir, accounts.PROFILE_NAME, "Preferences"),
			encoding="utf-8") as handle:
			return json.load(handle).get("account_info") or []
	except (OSError, ValueError):
		return []


def read_profile_email(profile_dir: str) -> str:
	"""Which Microsoft account a browser profile is signed into, for display.

	Read from the profile's own files rather than guessed from its folder name.
	The signed-in account wins over the recorded list: `account_info` keeps
	every account ever added to the profile, so its first entry can be an older,
	personal one that is not the account actually farming. Any failure - the
	profile not being created yet, or a file mid-write - falls back to a note,
	never an error.
	"""

	signed_in = _signed_in_profiles(profile_dir)
	opened = signed_in.get(accounts.PROFILE_NAME) or {}

	if opened.get("user_name"):
		return opened["user_name"]

	for entry in _recorded_accounts(profile_dir):
		if entry.get("email"):
			return entry["email"]

	for entry in signed_in.values():
		if entry.get("user_name"):
			return entry["user_name"]

	return "not signed in" if os.path.isdir(profile_dir) else "no folder yet"


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
	radius: float, **kwargs):
	"""A rounded rectangle, drawn as a smoothed polygon."""
	points = (
		x1 + radius, y1,
		x2 - radius, y1,
		x2, y1,
		x2, y1 + radius,
		x2, y2 - radius,
		x2, y2,
		x2 - radius, y2,
		x1 + radius, y2,
		x1, y2,
		x1, y2 - radius,
		x1, y1 + radius,
		x1, y1,
	)

	return canvas.create_polygon(points, smooth=True, **kwargs)


class ToggleSwitch(tk.Canvas):
	"""A small sliding switch bound to a BooleanVar.

	Tkinter has no switch widget, and the default checkbutton renders as a
	setting with no visible label next to it, which is easy to read as broken.
	This draws the familiar track-and-knob instead.
	"""

	WIDTH = 46
	HEIGHT = 24

	def __init__(self, parent, variable: tk.BooleanVar, **kwargs):
		super().__init__(parent, width=self.WIDTH, height=self.HEIGHT, bd=0,
			highlightthickness=0, bg=CARD_BG, cursor="hand2", **kwargs)
		self.variable = variable
		self.variable.trace_add("write", lambda *_args: self._draw())
		self.bind("<Button-1>", self._toggle)
		self._draw()

	def _draw(self) -> None:
		self.delete("all")
		on = self.variable.get()

		_round_rect(self, 1, 3, self.WIDTH - 1, self.HEIGHT - 3, 9,
			fill=ACCENT if on else TRACK_OFF, outline="")

		centre = 36 if on else 10
		self.create_oval(centre - 8, 4, centre + 8, 20, fill="#ffffff", outline="")

	def _toggle(self, _event=None) -> None:
		self.variable.set(not self.variable.get())


class TkLogHandler(logging.Handler):
	"""Send log records to the console widget, from any thread.

	`emit_line` is expected to be thread-safe - here it only queues the line,
	which the main loop then draws.
	"""

	def __init__(self, emit_line):
		super().__init__()
		self.emit_line = emit_line
		self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

	def emit(self, record):
		try:
			self.emit_line(self.format(record))
		except Exception:
			self.handleError(record)


class ManagerApp:
	def __init__(self, root: tk.Tk):
		self.root = root
		self.env = EnvFile(DOTENV_PATH)
		self.queue: queue.Queue = queue.Queue()

		self.process: subprocess.Popen | None = None
		self.signin_active = False
		self.stopping = False
		self.fields: dict[str, tuple] = {}

		self.views: dict[str, ttk.Frame] = {}
		self.nav: dict[str, tuple] = {}
		self.current_view = "Run"
		self._status: tuple | None = None

		# Filled by refresh_accounts: the configured names, the ones left out of
		# a run, and those left out in the account list's own order.
		self.accounts: list[str] = []
		self.excluded: set[str] = set()
		self.farming: list[str] = []
		self._skipped: list[str] = []

		self.theme = apply_palette(self._saved_theme())

		self._configure_window()
		self._build_chrome()
		self._install_log_handler()

		self.load_settings()
		self.refresh_accounts()

		self.root.protocol("WM_DELETE_WINDOW", self.on_close)
		self.root.after(80, self._drain_queue)

	# region window chrome

	def _configure_window(self) -> None:
		self.root.title("Rewards Farmer")
		self.root.configure(bg=APP_BG)
		self.root.minsize(780, 540)

		width, height = 940, 680
		screen_w = self.root.winfo_screenwidth()
		screen_h = self.root.winfo_screenheight()
		x = max(0, (screen_w - width) // 2)
		y = max(0, (screen_h - height) // 3)

		self.root.geometry(f"{width}x{height}+{x}+{y}")

	def _configure_style(self) -> None:
		style = ttk.Style(self.root)

		try:
			style.theme_use("clam")
		except tk.TclError:
			pass

		style.configure(".", background=APP_BG, foreground=TEXT, font=BASE_FONT, borderwidth=0)
		style.configure("TFrame", background=APP_BG)
		style.configure("Card.TFrame", background=CARD_BG)
		style.configure("TLabel", background=APP_BG, foreground=TEXT)
		style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT)
		style.configure("Muted.TLabel", background=APP_BG, foreground=MUTED)
		style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED)
		style.configure("H1.TLabel", background=CARD_BG, foreground=TEXT, font=SECTION_FONT)
		style.configure("Value.TLabel", background=CARD_BG, foreground=TEXT, font=BOLD_FONT)

		style.configure("TButton", font=BASE_FONT, padding=(12, 6), background=CARD_BG,
			foreground=TEXT, bordercolor=BORDER, focusthickness=0)
		style.map("TButton",
			background=[("active", BTN_HOVER), ("disabled", CARD_BG)],
			foreground=[("disabled", MUTED)])

		style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
			bordercolor=ACCENT)
		style.map("Accent.TButton",
			background=[("active", ACCENT_ACTIVE), ("disabled", ACCENT_DISABLED)],
			foreground=[("disabled", "#f0f0f0")])

		style.configure("Ghost.TButton", background=CARD_BG, foreground=ACCENT,
			bordercolor=BORDER)
		style.map("Ghost.TButton",
			background=[("active", GHOST_HOVER)],
			foreground=[("disabled", MUTED)])

		style.configure("Header.TButton", background=HEADER_BG, foreground=MUTED,
			bordercolor=HEADER_BG, padding=(10, 4))
		style.map("Header.TButton",
			background=[("active", BTN_HOVER)],
			foreground=[("active", TEXT)])

		style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT,
			bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=4)
		style.map("TEntry", bordercolor=[("focus", ACCENT)])

		style.configure("TCombobox", fieldbackground=INPUT_BG, foreground=TEXT,
			background=INPUT_BG, bordercolor=BORDER, arrowcolor=MUTED, padding=4)
		style.map("TCombobox", bordercolor=[("focus", ACCENT)])

		style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT,
			focusthickness=0)
		style.map("TCheckbutton", background=[("active", CARD_BG)])

		# The treeview and its headings default to the platform's own colours,
		# which stay light in the Dark palette unless they are set here.
		style.configure("Treeview", background=CARD_BG, fieldbackground=CARD_BG,
			foreground=TEXT, bordercolor=BORDER, rowheight=24)
		style.configure("Treeview.Heading", background=APP_BG, foreground=MUTED,
			bordercolor=BORDER)
		style.map("Treeview",
			background=[("selected", ACCENT)],
			foreground=[("selected", "#ffffff")])

		style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=APP_BG,
			bordercolor=APP_BG, arrowcolor=MUTED, relief="flat")

	def _build_chrome(self) -> None:
		"""Draw the whole window. Called again, from scratch, on a theme switch.

		The widgets are recreated rather than restyled because almost every
		colour here is a per-widget option; rebuilding is shorter and leaves no
		stale colours behind.
		"""

		self.views = {}
		self.nav = {}
		self.fields = {}

		self.root.configure(bg=APP_BG)
		self._configure_style()
		self._build_header()
		self._build_body()
		self._build_status_bar()

		if getattr(self, "_status", None):
			self.set_status(*self._status)

	def _saved_theme(self) -> str:
		stored = self.env.get(THEME_ENV_KEY, "").strip()
		return stored if stored in PALETTES else detect_system_theme()

	def _update_theme_button(self) -> None:
		other = "Light" if self.theme == "Dark" else "Dark"
		self.theme_button.configure(text=f"{other} mode")

	def toggle_theme(self) -> None:
		self.set_theme("Dark" if self.theme == "Light" else "Light")

	def set_theme(self, name: str) -> None:
		if name not in PALETTES:
			name = "Light"

		if name == self.theme:
			return

		# A switch redraws everything, so keep what the user would notice
		# losing: the log so far, the visible page, and any edits not yet saved.
		console_text = self.console.get("1.0", "end-1c")
		view = self.current_view
		values = {key: getter() for key, (getter, _setter, _spec) in self.fields.items()}

		self.theme = apply_palette(name)
		self.env.update({THEME_ENV_KEY: self.theme})

		for child in self.root.winfo_children():
			child.destroy()

		self._build_chrome()
		self.load_settings()

		for key, value in values.items():
			if key in self.fields:
				self.fields[key][1](value)

		self._show_view(view)
		self.refresh_accounts()

		if console_text:
			self.console.configure(state="normal")
			self.console.insert("1.0", console_text)
			self.console.configure(state="disabled")
			self.console.see("end")

		self.set_footer(f"{self.theme} theme.")

	def _build_header(self) -> None:
		header = tk.Frame(self.root, bg=HEADER_BG)
		header.pack(fill="x", side="top")

		inner = tk.Frame(header, bg=HEADER_BG, padx=22, pady=16)
		inner.pack(fill="x")

		titles = tk.Frame(inner, bg=HEADER_BG)
		titles.pack(side="left", anchor="w")

		tk.Label(titles, text="Rewards Farmer", bg=HEADER_BG, fg=TEXT,
			font=TITLE_FONT).pack(anchor="w")
		tk.Label(titles, text="Microsoft Rewards automation manager", bg=HEADER_BG,
			fg=MUTED, font=BASE_FONT).pack(anchor="w")

		self.status_label = tk.Label(inner, text="Idle", bg=HEADER_BG, fg=MUTED,
			font=BASE_FONT)
		self.status_label.pack(side="right", anchor="e")

		self.status_dot = tk.Canvas(inner, width=12, height=12, bg=HEADER_BG,
			highlightthickness=0)
		self.status_dot.pack(side="right", anchor="e", padx=(0, 8))
		self.status_dot_id = self.status_dot.create_oval(2, 2, 10, 10, fill=IDLE, outline="")

		self.theme_button = ttk.Button(inner, style="Header.TButton",
			command=self.toggle_theme)
		self.theme_button.pack(side="right", anchor="e", padx=(0, 18))
		self._update_theme_button()

		tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", side="top")

	def _build_status_bar(self) -> None:
		tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", side="bottom")

		bar = tk.Frame(self.root, bg=HEADER_BG)
		bar.pack(fill="x", side="bottom")

		self.footer_label = tk.Label(bar, text="Ready", bg=HEADER_BG, fg=MUTED,
			font=("Segoe UI", 9), padx=22, pady=6, anchor="w")
		self.footer_label.pack(side="left")

		tk.Label(bar, text=".env", bg=HEADER_BG, fg=IDLE, font=("Segoe UI", 9),
			padx=22, pady=6).pack(side="right")

	def _build_body(self) -> None:
		body = tk.Frame(self.root, bg=APP_BG)
		body.pack(fill="both", expand=True)

		sidebar = tk.Frame(body, bg=SIDEBAR_BG, width=208)
		sidebar.pack(side="left", fill="y")
		sidebar.pack_propagate(False)

		tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

		nav = tk.Frame(sidebar, bg=SIDEBAR_BG)
		nav.pack(fill="x", pady=(14, 0))

		content = tk.Frame(body, bg=APP_BG)
		content.pack(side="left", fill="both", expand=True)
		content.rowconfigure(0, weight=1)
		content.columnconfigure(0, weight=1)

		for name in ("Run", "Accounts", "Settings"):
			view = ttk.Frame(content)
			view.grid(row=0, column=0, sticky="nsew")
			self.views[name] = view

		for name in ("Run", "Accounts", "Settings"):
			self._add_nav_item(nav, name)

		self._build_run_view(self.views["Run"])
		self._build_accounts_view(self.views["Accounts"])
		self._build_settings_view(self.views["Settings"])

		self._show_view("Run")

	# endregion

	# region navigation

	def _add_nav_item(self, parent: tk.Frame, name: str) -> None:
		item = tk.Frame(parent, bg=SIDEBAR_BG, cursor="hand2")
		item.pack(fill="x", padx=8, pady=1)

		indicator = tk.Frame(item, bg=SIDEBAR_BG, width=3)
		indicator.pack(side="left", fill="y")

		label = tk.Label(item, text=name, bg=SIDEBAR_BG, fg=MUTED, anchor="w",
			font=BASE_FONT, padx=14, pady=9, cursor="hand2")
		label.pack(side="left", fill="x", expand=True)

		self.nav[name] = (item, indicator, label)

		for widget in (item, label):
			widget.bind("<Button-1>", lambda _event, n=name: self._show_view(n))
			widget.bind("<Enter>", lambda _event, n=name: self._nav_hover(n, True))
			widget.bind("<Leave>",
				lambda event, n=name: self._nav_hover(n, False, event))

	def _nav_hover(self, name: str, entering: bool, event=None) -> None:
		if name == self.current_view:
			return

		# Moving onto the label or the indicator counts as leaving the frame,
		# which would flicker the highlight back off. Ignore those.
		if not entering and event is not None and event.detail == "NotifyInferior":
			return

		background = NAV_HOVER if entering else SIDEBAR_BG
		item, _indicator, label = self.nav[name]
		item.configure(bg=background)
		label.configure(bg=background)

	def _show_view(self, name: str) -> None:
		self.current_view = name
		self.views[name].tkraise()

		for other, (item, indicator, label) in self.nav.items():
			selected = other == name
			background = NAV_SELECTED if selected else SIDEBAR_BG

			item.configure(bg=background)
			indicator.configure(bg=ACCENT if selected else SIDEBAR_BG)
			label.configure(bg=background, fg=ACCENT if selected else MUTED,
				font=BOLD_FONT if selected else BASE_FONT)

	# endregion

	# region run view

	def _build_run_view(self, tab: ttk.Frame) -> None:
		tab.columnconfigure(0, weight=1)
		tab.rowconfigure(1, weight=1)

		card = ttk.Frame(tab, style="Card.TFrame", padding=16)
		card.grid(row=0, column=0, sticky="ew", pady=(18, 0), padx=18)
		card.columnconfigure(0, weight=1)

		left = ttk.Frame(card, style="Card.TFrame")
		left.grid(row=0, column=0, sticky="w")

		ttk.Label(left, text="Accounts to run", style="CardMuted.TLabel").grid(
			row=0, column=0, sticky="w")
		self.run_accounts_label = ttk.Label(left, text="-", style="Value.TLabel",
			wraplength=520, justify="left")
		self.run_accounts_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
		self.run_excluded_label = ttk.Label(left, text="", style="CardMuted.TLabel",
			wraplength=520, justify="left")
		self.run_excluded_label.grid(row=2, column=0, sticky="w", pady=(2, 0))

		actions = ttk.Frame(card, style="Card.TFrame")
		actions.grid(row=0, column=1, sticky="e")

		self.run_button = ttk.Button(actions, text="Run", style="Accent.TButton",
			command=self.start_run, width=10)
		self.run_button.grid(row=0, column=0, padx=(0, 8))

		self.stop_button = ttk.Button(actions, text="Stop", command=self.stop_run,
			state="disabled", width=10)
		self.stop_button.grid(row=0, column=1)

		console_card = ttk.Frame(tab, style="Card.TFrame", padding=(16, 12, 16, 16))
		console_card.grid(row=1, column=0, sticky="nsew", pady=(12, 18), padx=18)
		console_card.columnconfigure(0, weight=1)
		console_card.rowconfigure(1, weight=1)

		head = ttk.Frame(console_card, style="Card.TFrame")
		head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
		head.columnconfigure(0, weight=1)

		ttk.Label(head, text="Output", style="H1.TLabel").grid(row=0, column=0, sticky="w")
		ttk.Button(head, text="Clear", style="Ghost.TButton",
			command=self.clear_console).grid(row=0, column=1, sticky="e")

		self.console = tk.Text(console_card, bg=CONSOLE_BG, fg=CONSOLE_FG, bd=0,
			relief="flat", wrap="word", font=MONO_FONT, padx=12, pady=10,
			highlightthickness=0, insertbackground=CONSOLE_FG, state="disabled")

		scrollbar = ttk.Scrollbar(console_card, orient="vertical",
			command=self.console.yview)
		self.console.configure(yscrollcommand=scrollbar.set)

		self.console.grid(row=1, column=0, sticky="nsew")
		scrollbar.grid(row=1, column=1, sticky="ns")

		self.console.tag_configure("error", foreground=CONSOLE_ERROR)
		self.console.tag_configure("warning", foreground=CONSOLE_WARNING)
		self.console.tag_configure("success", foreground=CONSOLE_SUCCESS)
		self.console.tag_configure("muted", foreground=CONSOLE_MUTED)

	# endregion

	# region accounts view

	def _build_accounts_view(self, tab: ttk.Frame) -> None:
		tab.columnconfigure(0, weight=1)
		tab.rowconfigure(0, weight=1)

		card = ttk.Frame(tab, style="Card.TFrame", padding=16)
		card.grid(row=0, column=0, sticky="nsew", pady=(18, 18), padx=18)
		card.columnconfigure(0, weight=1)
		card.rowconfigure(2, weight=1)

		head = ttk.Frame(card, style="Card.TFrame")
		head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
		head.columnconfigure(0, weight=1)

		ttk.Label(head, text="Accounts", style="H1.TLabel").grid(row=0, column=0, sticky="w")
		self.accounts_count_label = ttk.Label(head, text="", style="CardMuted.TLabel")
		self.accounts_count_label.grid(row=0, column=1, sticky="e")

		ttk.Label(card, style="CardMuted.TLabel", wraplength=660, justify="left",
			text="Each account is its own browser profile under the data directory. "
			     "The second column is the Microsoft account that profile is signed "
			     "into - the one a run actually farms. Every account runs by default; "
			     "select rows and Exclude the ones you want left out. Double-clicking "
			     "a row flips it. Sign in once per profile, then a run works through "
			     "the rest in order.").grid(
			row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))

		self.accounts_tree = ttk.Treeview(card, columns=("name", "email", "run"),
			show="headings", selectmode="extended", height=10)
		self.accounts_tree.heading("name", text="Profile directory")
		self.accounts_tree.heading("email", text="Signed in as")
		self.accounts_tree.heading("run", text="Run")
		self.accounts_tree.column("name", anchor="w", width=200, stretch=False)
		self.accounts_tree.column("email", anchor="w", width=320)
		self.accounts_tree.column("run", anchor="w", width=80, stretch=False)
		# An excluded row stays readable but recedes, so the farming set is
		# obvious at a glance.
		self.accounts_tree.tag_configure("skipped", foreground=MUTED)
		self.accounts_tree.grid(row=2, column=0, sticky="nsew")
		self.accounts_tree.bind("<Double-1>", self._toggle_row)
		self.accounts_tree.bind("<space>", self._toggle_selected_rows)

		tree_scroll = ttk.Scrollbar(card, orient="vertical",
			command=self.accounts_tree.yview)
		self.accounts_tree.configure(yscrollcommand=tree_scroll.set)
		tree_scroll.grid(row=2, column=1, sticky="ns")

		add_row = ttk.Frame(card, style="Card.TFrame")
		add_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
		add_row.columnconfigure(1, weight=1)

		ttk.Label(add_row, text="New profile", style="Card.TLabel").grid(
			row=0, column=0, sticky="w", padx=(0, 10))
		self.new_account_var = tk.StringVar()
		entry = ttk.Entry(add_row, textvariable=self.new_account_var)
		entry.grid(row=0, column=1, sticky="ew")
		entry.bind("<Return>", lambda _event: self.add_account())
		ttk.Button(add_row, text="Add", style="Accent.TButton",
			command=self.add_account, width=8).grid(row=0, column=2, padx=(8, 0))
		ttk.Button(add_row, text="Add many...", style="Ghost.TButton",
			command=self.add_accounts_dialog, width=12).grid(row=0, column=3, padx=(8, 0))

		action_row = ttk.Frame(card, style="Card.TFrame")
		action_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
		action_row.columnconfigure(3, weight=1)

		ttk.Button(action_row, text="Select all", style="Ghost.TButton",
			command=self.select_all_accounts, width=10).grid(row=0, column=0, padx=(0, 8))
		ttk.Button(action_row, text="Include", style="Ghost.TButton",
			command=self.include_accounts, width=9).grid(row=0, column=1, padx=(0, 8))
		ttk.Button(action_row, text="Exclude", style="Ghost.TButton",
			command=self.exclude_accounts, width=9).grid(row=0, column=2)

		self.signin_button = ttk.Button(action_row, text="Sign in", style="Ghost.TButton",
			command=self.sign_in, width=10)
		self.signin_button.grid(row=0, column=4, padx=(8, 8))
		self.remove_button = ttk.Button(action_row, text="Remove", style="Ghost.TButton",
			command=self.remove_accounts, width=10)
		self.remove_button.grid(row=0, column=5)

	# endregion

	# region settings view

	def _build_settings_view(self, tab: ttk.Frame) -> None:
		tab.columnconfigure(0, weight=1)
		tab.rowconfigure(0, weight=1)

		card = ttk.Frame(tab, style="Card.TFrame", padding=(16, 16, 16, 0))
		card.grid(row=0, column=0, sticky="nsew", pady=(18, 18), padx=18)
		card.columnconfigure(0, weight=1)
		card.rowconfigure(1, weight=1)

		head = ttk.Frame(card, style="Card.TFrame")
		head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
		ttk.Label(head, text="Settings", style="H1.TLabel").pack(side="left")
		ttk.Label(head, text="  stored in .env", style="CardMuted.TLabel").pack(side="left")

		body = self._scrollable(card)

		for section in SETTINGS:
			self._build_section(body, section)

		actions = ttk.Frame(card, style="Card.TFrame", padding=(0, 12))
		actions.grid(row=2, column=0, sticky="ew")
		actions.columnconfigure(0, weight=1)

		ttk.Button(actions, text="Reload from .env", style="Ghost.TButton",
			command=self.load_settings).grid(row=0, column=0, sticky="w")
		ttk.Button(actions, text="Save", style="Accent.TButton",
			command=self.save_settings, width=12).grid(row=0, column=1, sticky="e")

	def _scrollable(self, parent: ttk.Frame) -> ttk.Frame:
		canvas = tk.Canvas(parent, bg=CARD_BG, highlightthickness=0, bd=0)
		scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
		canvas.configure(yscrollcommand=scrollbar.set)

		canvas.grid(row=1, column=0, sticky="nsew")
		scrollbar.grid(row=1, column=1, sticky="ns")

		inner = ttk.Frame(canvas, style="Card.TFrame")
		window = canvas.create_window((0, 0), window=inner, anchor="nw")

		inner.bind("<Configure>",
			lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
		canvas.bind("<Configure>",
			lambda event: canvas.itemconfigure(window, width=event.width))

		def on_wheel(event):
			canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

		# Bound only while the pointer is over the settings pane, so it does
		# not swallow the wheel elsewhere in the window.
		canvas.bind("<Enter>", lambda _event: self.root.bind_all("<MouseWheel>", on_wheel))
		canvas.bind("<Leave>", lambda _event: self.root.unbind_all("<MouseWheel>"))

		return inner

	def _build_section(self, parent: ttk.Frame, section: Section) -> None:
		block = ttk.Frame(parent, style="Card.TFrame", padding=(0, 6))
		block.pack(fill="x")
		block.columnconfigure(1, weight=1)

		ttk.Label(block, text=section.title, style="H1.TLabel").grid(
			row=0, column=0, columnspan=3, sticky="w", pady=(4, 2))

		for index, spec in enumerate(section.fields, start=1):
			self._build_field(block, index, spec)

		separator = tk.Frame(block, bg=BORDER, height=1)
		separator.grid(row=len(section.fields) + 1, column=0, columnspan=3,
			sticky="ew", pady=(12, 2))

	def _build_field(self, parent: ttk.Frame, row: int, spec: Field) -> None:
		ttk.Label(parent, text=spec.label, style="Card.TLabel").grid(
			row=row, column=0, sticky="w", padx=(0, 16), pady=5)

		current = self.env.get(spec.key, spec.default)

		if spec.kind == "bool":
			var = tk.BooleanVar(value=_to_bool(current))

			holder = ttk.Frame(parent, style="Card.TFrame")
			holder.grid(row=row, column=1, sticky="w", pady=5)

			ToggleSwitch(holder, var).pack(side="left")

			state_label = ttk.Label(holder, text="", style="CardMuted.TLabel", width=3)
			state_label.pack(side="left", padx=(10, 0))

			def sync_state(*_args, var=var, state_label=state_label):
				state_label.configure(text="On" if var.get() else "Off")

			var.trace_add("write", sync_state)
			sync_state()

			getter = lambda var=var: "true" if var.get() else "false"
			setter = lambda value, var=var: var.set(_to_bool(value))

		elif spec.kind == "choice":
			var = tk.StringVar(value=current if current in spec.choices else spec.default)
			widget = ttk.Combobox(parent, textvariable=var, values=list(spec.choices),
				state="readonly", width=26)
			widget.grid(row=row, column=1, sticky="w", pady=5)
			getter = lambda var=var, default=spec.default: var.get() or default
			setter = lambda value, var=var, choices=spec.choices, default=spec.default: var.set(
				value if value in choices else default)

		else:
			var = tk.StringVar(value=current)
			widget = ttk.Entry(parent, textvariable=var)
			widget.grid(row=row, column=1, sticky="ew", pady=5)
			getter = lambda var=var: var.get().strip()
			setter = lambda value, var=var: var.set(value)

			if spec.browse:
				mode = spec.browse
				button = ttk.Button(parent, text="Browse", style="Ghost.TButton",
					width=9, command=lambda var=var, mode=mode: self._browse(var, mode))
				button.grid(row=row, column=2, sticky="e", padx=(8, 0))

		self.fields[spec.key] = (getter, setter, spec)

	def _browse(self, var: tk.StringVar, mode: str) -> None:
		if mode == "dir":
			chosen = filedialog.askdirectory(initialdir=var.get() or REPO_ROOT)
		else:
			chosen = filedialog.askopenfilename(initialdir=var.get() or REPO_ROOT)

		if chosen:
			var.set(chosen)

	# endregion

	# region settings load/save

	def load_settings(self) -> None:
		for field in ALL_FIELDS:
			getter, setter, spec = self.fields[field.key]
			setter(self.env.get(spec.key, spec.default))

		self.set_footer("Settings loaded from .env")

	def save_settings(self) -> None:
		updates: dict[str, str] = {}
		problems: list[str] = []

		for field in ALL_FIELDS:
			getter, _setter, spec = self.fields[field.key]
			value = getter()

			if value and spec.kind in ("int", "float"):
				try:
					int(value) if spec.kind == "int" else float(value)
				except ValueError:
					problems.append(f"{spec.label} must be a number.")

			updates[field.key] = value

		if problems:
			messagebox.showerror("Cannot save", "\n".join(problems), parent=self.root)
			return

		try:
			self.env.update(updates)
		except OSError as exc:
			messagebox.showerror("Cannot save", f"Could not write .env:\n{exc}",
				parent=self.root)
			return

		self.reload_environment()
		self.refresh_accounts()
		self.set_footer("Settings saved to .env")
		messagebox.showinfo("Saved", "Settings saved to .env.", parent=self.root)

	def reload_environment(self) -> None:
		"""Make the just-saved file the values this process hands to a browser."""
		dotenv.load_dotenv(self.env.path, override=True)

	# endregion

	# region accounts

	def refresh_accounts(self) -> None:
		self.accounts = split_account_names(self.env.get("REWARDS_ACCOUNTS", ""))
		self.excluded, self._skipped = self._read_exclusions()

		for item in self.accounts_tree.get_children():
			self.accounts_tree.delete(item)

		for name in self.accounts:
			skipped = name in self.excluded
			self.accounts_tree.insert("", "end",
				values=(name, self._profile_email(name), "Skipped" if skipped else "Farms"),
				tags=("skipped",) if skipped else ())

		self.farming = [name for name in self.accounts if name not in self.excluded]
		self._refresh_run_label()
		self._refresh_accounts_count()

		self._update_controls()

	def _read_exclusions(self) -> tuple[set[str], list[str]]:
		"""The excluded names, plus the subset of them that is still configured.

		The second value is the prune list, so a name that was removed from the
		accounts is also dropped from the exclude list the next time this runs.
		"""
		configured = {name.lower(): name for name in self.accounts}
		raw = split_account_names(self.env.get(EXCLUDE_ENV_KEY, ""))

		# Store each exclusion under the account list's own spelling, so the
		# two lists cannot drift apart in case.
		excluded = {configured[name.lower()] for name in raw if name.lower() in configured}
		skipped = [name for name in self.accounts if name in excluded]

		return excluded, skipped

	def _refresh_run_label(self) -> None:
		if not self.accounts:
			self.run_accounts_label.configure(text="(default profile)")
			self.run_excluded_label.configure(text="The default profile will run.")
			return

		self.run_accounts_label.configure(
			text=", ".join(self.farming) if self.farming else "(nothing selected)")

		if self._skipped:
			self.run_excluded_label.configure(
				text=f"{len(self.farming)} of {len(self.accounts)} will run. "
				     f"Excluded: {', '.join(self._skipped)}.")
		else:
			self.run_excluded_label.configure(text=f"All {len(self.accounts)} will run.")

	def _refresh_accounts_count(self) -> None:
		count = len(self.accounts)
		skipped = len(self._skipped)
		if not count:
			text = "0 accounts"
		elif skipped:
			text = f"{count} accounts, {skipped} excluded"
		else:
			text = f"{count} account{'s' if count != 1 else ''}"
		self.accounts_count_label.configure(text=text)

	def _profile_email(self, name: str) -> str:
		root = os.environ.get(accounts.DATA_DIR_ENV_VAR, DEFAULT_ROOT_DATA_DIR)
		return read_profile_email(os.path.join(root, name))

	def add_account(self) -> None:
		names = split_account_names(self.new_account_var.get())

		if not names:
			messagebox.showwarning("Add account", "Enter a name for the profile.",
				parent=self.root)
			return

		if self._add_names(names):
			self.new_account_var.set("")

	def add_accounts_dialog(self) -> None:
		"""A multi-line box for pasting a whole list of profile names at once."""

		dialog = tk.Toplevel(self.root)
		dialog.title("Add accounts")
		dialog.configure(bg=CARD_BG)
		dialog.transient(self.root)

		wrapper = tk.Frame(dialog, bg=CARD_BG, padx=16, pady=14)
		wrapper.pack(fill="both", expand=True)

		tk.Label(wrapper, text="One profile name per line", bg=CARD_BG, fg=TEXT,
			font=BOLD_FONT).pack(anchor="w")
		tk.Label(wrapper, bg=CARD_BG, fg=MUTED, font=BASE_FONT, justify="left",
			text="Letters, digits, dot, dash or underscore. Commas and blank "
			     "lines are fine too; duplicates are skipped.").pack(anchor="w", pady=(2, 8))

		text = tk.Text(wrapper, width=44, height=12, bg=INPUT_BG, fg=TEXT,
			insertbackground=TEXT, bd=0, highlightthickness=1,
			highlightbackground=BORDER, highlightcolor=ACCENT, font=BASE_FONT,
			padx=8, pady=6, wrap="none")
		text.pack(fill="both", expand=True)
		text.focus_set()

		buttons = tk.Frame(wrapper, bg=CARD_BG)
		buttons.pack(fill="x", pady=(10, 0))

		def submit():
			names = split_account_names(text.get("1.0", "end"))
			dialog.destroy()
			if names:
				self._add_names(names)

		ttk.Button(buttons, text="Add", style="Accent.TButton", command=submit,
			width=10).pack(side="right")
		ttk.Button(buttons, text="Cancel", style="Ghost.TButton",
			command=dialog.destroy, width=10).pack(side="right", padx=(0, 8))

		dialog.bind("<Escape>", lambda _event: dialog.destroy())
		dialog.update_idletasks()
		x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
		y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 3
		dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
		dialog.grab_set()

	def _add_names(self, names: list[str]) -> list[str]:
		"""Add the valid, not-already-present names. Returns the ones added."""

		existing = {name.lower() for name in self.accounts}
		added: list[str] = []
		rejected: list[str] = []
		duplicates: list[str] = []

		for name in names:
			if not accounts.directory_name_is_valid(name):
				rejected.append(name)
			elif name.lower() in existing:
				duplicates.append(name)
			else:
				existing.add(name.lower())
				self.accounts.append(name)
				added.append(name)

		if added:
			self._write_accounts()
			self.set_footer(
				f"Added {len(added)} account{'s' if len(added) != 1 else ''}. "
				"Sign in to each before a run.")

		if rejected:
			messagebox.showwarning("Add account",
				"Skipped names that cannot be folder names:\n\n" + "\n".join(rejected),
				parent=self.root)
		elif duplicates:
			messagebox.showinfo("Add account",
				"Already configured, so left alone:\n\n" + "\n".join(duplicates),
				parent=self.root)

		return added

	def remove_accounts(self) -> None:
		selected = self._selected_accounts()

		if not selected:
			messagebox.showinfo("Remove account", "Select an account to remove.",
				parent=self.root)
			return

		what = f"{len(selected)} accounts" if len(selected) > 1 else f"'{selected[0]}'"
		if not messagebox.askyesno("Remove account",
			f"Remove {what} from the list?\n\nThe profile director"
			f"{'ies' if len(selected) > 1 else 'y'} on disk "
			f"{'are' if len(selected) > 1 else 'is'} left where "
			f"{'they are' if len(selected) > 1 else 'it is'}.",
			parent=self.root):
			return

		self.accounts = [name for name in self.accounts if name not in selected]
		self._write_accounts()
		self.set_footer(f"Removed {what}.")

	def select_all_accounts(self) -> None:
		self.accounts_tree.selection_set(self.accounts_tree.get_children())

	def include_accounts(self) -> None:
		self._set_excluded(self._selected_accounts(), False)

	def exclude_accounts(self) -> None:
		self._set_excluded(self._selected_accounts(), True)

	def _toggle_row(self, event) -> None:
		"""Double-click: flip one row between farming and skipped."""
		item = self.accounts_tree.identify_row(event.y)

		if item:
			self._toggle_items([item])

	def _toggle_selected_rows(self, _event) -> str:
		"""Space: flip every selected row, then stop Tk's default handling."""
		self._toggle_items(self.accounts_tree.selection())
		return "break"

	def _toggle_items(self, items) -> None:
		names = [self.accounts_tree.item(item, "values")[0] for item in items]

		if not names:
			return

		# Flip each row on its own, so a mixed selection ends up mixed the
		# other way rather than all collapsing to one state.
		for name in names:
			if name in self.excluded:
				self.excluded.discard(name)
			else:
				self.excluded.add(name)

		self._save_exclusions()
		self.refresh_accounts()

	def _set_excluded(self, names: list[str], excluded: bool) -> None:
		"""Move the named accounts into or out of the exclude set, and save it."""
		if not names:
			messagebox.showinfo("Accounts",
				"Select one or more accounts first.", parent=self.root)
			return

		if excluded:
			self.excluded.update(names)
		else:
			self.excluded.difference_update(names)

		self._save_exclusions()
		self.refresh_accounts()

		verb = "Excluded" if excluded else "Included"
		count = len(names)
		self.set_footer(f"{verb} {count} account{'s' if count != 1 else ''}.")

	def _save_exclusions(self) -> None:
		# Written in the account list's order so the file stays readable.
		ordered = [name for name in self.accounts if name in self.excluded]
		self.env.update({EXCLUDE_ENV_KEY: ",".join(ordered)})

	def _write_accounts(self) -> None:
		self.env.update({"REWARDS_ACCOUNTS": ",".join(self.accounts)})
		# Keep the exclude list from keeping names that just left the accounts.
		self._save_exclusions()
		self.refresh_accounts()

	def _selected_accounts(self) -> list[str]:
		# selection() gives the tree's own item ids, not the names in them.
		return [
			self.accounts_tree.item(item, "values")[0]
			for item in self.accounts_tree.selection()
		]

	# endregion

	# region sign in

	def sign_in(self) -> None:
		selected = self._selected_accounts()

		if len(selected) != 1:
			messagebox.showinfo("Sign in", "Select exactly one account to sign in.",
				parent=self.root)
			return

		self.signin_active = True
		self._update_controls()
		self.set_status("running", f"Signing in to {selected[0]}...")
		self._show_view("Run")

		threading.Thread(target=self._sign_in_worker, args=(selected[0],),
			daemon=True).start()

	def _sign_in_worker(self, name: str) -> None:
		self.post(self.append_console, f"[gui] Opening Edge for '{name}' ...", "muted")

		try:
			self.reload_environment()
			account = self._account_object(name)
			driver = browser.start_driver(account)

			if driver is None:
				self.post(self.append_console,
					f"[gui] Could not start Edge for '{name}'. See the message above.",
					"error")
				return

			self.post(self.append_console,
				f"[gui] Sign in to '{name}' in the Edge window, then close it.", "muted")

			while True:
				try:
					driver.title
					time.sleep(0.5)
				except Exception:
					break

			try:
				driver.quit()
			except Exception:
				pass

			self.post(self.append_console, f"[gui] '{name}': browser closed.", "success")
		except Exception as exc:
			self.post(self.append_console, f"[gui] Sign in failed: {exc}", "error")
		finally:
			self.post(self._sign_in_finished)

	def _sign_in_finished(self) -> None:
		self.signin_active = False
		# The profile may have picked up a sign-in, so re-read the column.
		self.refresh_accounts()
		self._update_controls()
		self.set_status("idle", "Idle")

	def _account_object(self, name: str) -> accounts.Account:
		root = os.environ.get(accounts.DATA_DIR_ENV_VAR, DEFAULT_ROOT_DATA_DIR)

		return accounts.Account(
			name=name,
			user_data_dir=os.path.join(root, name),
			profile_name=accounts.PROFILE_NAME,
		)

	# endregion

	# region running

	def _run_environment(self) -> dict[str, str]:
		"""The environment for main.py: everything, with REWARDS_ACCOUNTS pinned.

		main.py loads `.env` without overriding, so the value set here is the
		one it works through, and the full list in the file is left alone. With
		no named accounts the variable is not set, so the default profile runs.
		"""
		environment = os.environ.copy()

		if self.accounts:
			environment[accounts.ACCOUNTS_ENV_VAR] = ",".join(self.farming)

		return environment

	def start_run(self) -> None:
		if self.process is not None:
			return

		if self.signin_active:
			messagebox.showinfo("Run", "A sign-in is in progress. Wait for it to finish.",
				parent=self.root)
			return

		# Pick up the file as it is now, including edits made outside this
		# window since it opened. main.py loads .env too, but not over values
		# already in the environment, and a sign-in may have put older ones
		# there.
		self.reload_environment()
		self.refresh_accounts()

		enabled = self.farming

		if self.accounts and not enabled:
			messagebox.showinfo("Run",
				"Every account is excluded. Include at least one on the Accounts tab.",
				parent=self.root)
			return

		self.clear_console()
		self.append_console("[gui] Starting rewards-farmer ...", "muted")
		self.stopping = False

		if self.accounts:
			self.append_console(
				f"[gui] Farming {len(enabled)} of {len(self.accounts)}: "
				f"{', '.join(enabled)}", "muted")
		else:
			self.append_console("[gui] Farming the default profile.", "muted")

		# main.py loads .env without overriding, so a REWARDS_ACCOUNTS put here
		# is the set it actually works through. The full list stays in the file.
		run_env = self._run_environment()

		command = [sys.executable, "-u", MAIN_SCRIPT]
		creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

		try:
			self.process = subprocess.Popen(
				command,
				env=run_env,
				cwd=REPO_ROOT,
				stdin=subprocess.DEVNULL,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				encoding="utf-8",
				errors="replace",
				bufsize=1,
				creationflags=creationflags,
			)
		except OSError as exc:
			self.process = None
			self.append_console(f"[gui] Could not start main.py: {exc}", "error")
			messagebox.showerror("Run", f"Could not start the bot:\n{exc}", parent=self.root)
			return

		self.set_status("running", "Running...")
		self._update_controls()

		threading.Thread(target=self._read_output, args=(self.process,),
			daemon=True).start()

	def _read_output(self, process: subprocess.Popen) -> None:
		try:
			if process.stdout is not None:
				for line in process.stdout:
					self.post(self.append_console, line.rstrip("\n"))
		finally:
			code = process.wait()
			self.post(self._run_finished, code)

	def stop_run(self) -> None:
		if self.process is None:
			return

		self.stopping = True
		self.set_status("running", "Stopping...")
		self.stop_button.configure(state="disabled")

		try:
			self._terminate(self.process)
		except Exception as exc:
			self.append_console(f"[gui] Could not stop the bot cleanly: {exc}", "error")

	def _terminate(self, process: subprocess.Popen) -> None:
		if os.name == "nt":
			subprocess.run(
				["taskkill", "/F", "/T", "/PID", str(process.pid)],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
				creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
			)
		else:
			process.terminate()

	def _run_finished(self, code: int) -> None:
		self.process = None

		if self.stopping:
			self.stopping = False
			self.append_console("[gui] Stopped.", "muted")
			self.set_status("idle", "Stopped")
		elif code == 0:
			self.append_console("[gui] Finished.", "success")
			self.set_status("success", "Finished")
		else:
			self.append_console(f"[gui] Exited with code {code}.", "error")
			self.set_status("error", f"Exited with code {code}")

		self._update_controls()

	# endregion

	# region console and status

	def append_console(self, line: str, tag: str | None = None) -> None:
		if tag is None:
			tag = self._tag_for(line)

		self.console.configure(state="normal")
		self.console.insert("end", line + "\n", tag)

		# Trim the oldest lines so a long or chatty run cannot grow without end.
		total = int(self.console.index("end-1c").split(".")[0])
		if total > MAX_CONSOLE_LINES:
			self.console.delete("1.0", f"{total - MAX_CONSOLE_LINES}.0")

		self.console.see("end")
		self.console.configure(state="disabled")

	@staticmethod
	def _tag_for(line: str) -> str | None:
		if "[gui]" in line:
			return "muted"
		if "[FAIL]" in line or " ERROR " in f" {line} " or " CRITICAL " in f" {line} ":
			return "error"
		if " WARNING " in f" {line} ":
			return "warning"
		return None

	def clear_console(self) -> None:
		self.console.configure(state="normal")
		self.console.delete("1.0", "end")
		self.console.configure(state="disabled")

	def set_status(self, kind: str, text: str) -> None:
		self._status = (kind, text)
		colors = {"running": ACCENT, "success": SUCCESS, "error": DANGER, "idle": IDLE}
		self.status_dot.itemconfigure(self.status_dot_id, fill=colors.get(kind, IDLE))
		self.status_label.configure(text=text)

	def set_footer(self, text: str) -> None:
		self.footer_label.configure(text=text)

	def _update_controls(self) -> None:
		running = self.process is not None

		self.run_button.configure(state="disabled" if (running or self.signin_active) else "normal")
		self.stop_button.configure(state="normal" if running else "disabled")
		self.signin_button.configure(state="disabled" if (running or self.signin_active) else "normal")

	# endregion

	# region plumbing

	def _install_log_handler(self) -> None:
		handler = TkLogHandler(lambda line: self.post(self.append_console, line))
		handler.setLevel(logging.INFO)

		root_logger = logging.getLogger()
		root_logger.setLevel(logging.INFO)
		root_logger.addHandler(handler)

		for name in log_utils.NOISY_LIBRARIES:
			logging.getLogger(name).setLevel(logging.WARNING)

	def post(self, callback, *args) -> None:
		"""Queue work for the main thread; tkinter is not safe to touch off it."""
		self.queue.put((callback, args))

	def _drain_queue(self) -> None:
		while True:
			try:
				callback, args = self.queue.get_nowait()
			except queue.Empty:
				break

			try:
				callback(*args)
			except Exception:
				logging.getLogger(__name__).exception("GUI callback failed")

		self.root.after(80, self._drain_queue)

	def on_close(self) -> None:
		if self.process is not None:
			if not messagebox.askyesno("Quit", "A run is in progress. Stop it and quit?",
				parent=self.root):
				return

			try:
				self._terminate(self.process)
			except Exception:
				pass

		self.root.destroy()

	# endregion


def main() -> int:
	root = tk.Tk()
	ManagerApp(root)
	root.mainloop()

	return 0


if __name__ == "__main__":
	sys.exit(main())
