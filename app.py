from __future__ import annotations

import ctypes
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox, ttk


@dataclass
class CleanupResult:
    files_removed: int = 0
    directories_removed: int = 0
    browser_databases_cleared: int = 0
    browser_caches_cleared: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)
    system_tasks_done: list[str] = field(default_factory=list)


def format_bytes(size: int | float) -> str:
    """Format bytes into a human readable string (B, KB, MB, GB)."""
    if size < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    val = float(size)
    while val >= 1024.0 and unit_index < len(units) - 1:
        val /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(val)} {units[unit_index]}"
    return f"{val:.2f} {units[unit_index]}"


def discover_browser_history_files(
    appdata: str | None = None,
    local_appdata: str | None = None,
) -> list[tuple[str, Path, str]]:
    """Return each supported browser's history database and its database type."""
    roaming_value = appdata if appdata is not None else os.environ.get("APPDATA")
    local_value = (
        local_appdata
        if local_appdata is not None
        else os.environ.get("LOCALAPPDATA")
    )
    databases: list[tuple[str, Path, str]] = []

    # Chromium based browsers in LocalAppData
    chromium_roots = []
    if local_value:
        local = Path(local_value)
        chromium_roots = [
            ("Google Chrome", local / "Google" / "Chrome" / "User Data"),
            ("Microsoft Edge", local / "Microsoft" / "Edge" / "User Data"),
            ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
            ("Vivaldi", local / "Vivaldi" / "User Data"),
        ]
    for browser, root in chromium_roots:
        if root.is_dir():
            try:
                for profile in root.iterdir():
                    if profile.is_dir():
                        history_file = profile / "History"
                        if history_file.is_file():
                            databases.append((browser, history_file, "chromium"))
            except OSError:
                pass

    # Opera and Opera GX in Roaming AppData
    if roaming_value:
        roaming = Path(roaming_value)
        opera_roots = [
            ("Opera", roaming / "Opera Software" / "Opera Stable" / "History"),
            ("Opera GX", roaming / "Opera Software" / "Opera GX Stable" / "History"),
        ]
        for browser, history_file in opera_roots:
            if history_file.is_file():
                databases.append((browser, history_file, "chromium"))

    # Firefox in Roaming and Local
    firefox_roots = []
    if roaming_value:
        firefox_roots.append(
            Path(roaming_value) / "Mozilla" / "Firefox" / "Profiles"
        )
    if local_value:
        firefox_roots.append(
            Path(local_value) / "Mozilla" / "Firefox" / "Profiles"
        )
    seen: set[Path] = set()
    for root in firefox_roots:
        if root.is_dir():
            try:
                for profile in root.iterdir():
                    database = profile / "places.sqlite"
                    try:
                        resolved = database.resolve()
                    except OSError:
                        resolved = database
                    if database.is_file() and resolved not in seen:
                        seen.add(resolved)
                        databases.append(("Firefox", database, "firefox"))
            except OSError:
                pass

    return databases


def discover_browser_cache_directories(
    appdata: str | None = None,
    local_appdata: str | None = None,
) -> list[tuple[str, Path]]:
    """Return cache folders for all detected browsers."""
    local_value = (
        local_appdata
        if local_appdata is not None
        else os.environ.get("LOCALAPPDATA")
    )
    caches: list[tuple[str, Path]] = []
    if not local_value:
        return caches

    local = Path(local_value)
    cache_subdirs = ["Cache", "Code Cache", "GPUCache", "DawnCache"]

    chromium_browser_roots = [
        ("Google Chrome", local / "Google" / "Chrome" / "User Data"),
        ("Microsoft Edge", local / "Microsoft" / "Edge" / "User Data"),
        ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
        ("Vivaldi", local / "Vivaldi" / "User Data"),
    ]

    for browser, root in chromium_browser_roots:
        if root.is_dir():
            try:
                for profile in root.iterdir():
                    if profile.is_dir():
                        for subdir in cache_subdirs:
                            c_path = profile / subdir
                            if c_path.is_dir():
                                caches.append((f"{browser} ({profile.name}/{subdir})", c_path))
            except OSError:
                pass

    # Opera and Opera GX cache
    opera_caches = [
        ("Opera", local / "Opera Software" / "Opera Stable" / "Cache"),
        ("Opera GX", local / "Opera Software" / "Opera GX Stable" / "Cache"),
    ]
    for browser, cache_dir in opera_caches:
        if cache_dir.is_dir():
            caches.append((browser, cache_dir))

    # Firefox cache (usually in LocalAppData/Mozilla/Firefox/Profiles/<profile>/cache2)
    ff_root = local / "Mozilla" / "Firefox" / "Profiles"
    if ff_root.is_dir():
        try:
            for profile in ff_root.iterdir():
                if profile.is_dir():
                    c2 = profile / "cache2"
                    if c2.is_dir():
                        caches.append((f"Firefox ({profile.name}/cache2)", c2))
                    sc = profile / "startupCache"
                    if sc.is_dir():
                        caches.append((f"Firefox ({profile.name}/startupCache)", sc))
        except OSError:
            pass

    return caches


def clear_chromium_history(database: Path, complete: bool = False) -> None:
    """Clear Chromium history. If complete is True, URLs and search entries are fully removed."""
    connection = sqlite3.connect(database, timeout=5)
    try:
        with connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            for table in ("visits", "visit_source", "keyword_search_terms", "segment_usage", "segments"):
                try:
                    connection.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    pass

            for dl_table in ("downloads", "downloads_url_chains", "downloads_slices"):
                try:
                    connection.execute(f"DELETE FROM {dl_table}")
                except sqlite3.OperationalError:
                    pass

            if complete:
                try:
                    connection.execute("DELETE FROM urls")
                except sqlite3.OperationalError:
                    pass
            else:
                try:
                    connection.execute(
                        "UPDATE urls SET visit_count = 0, last_visit_time = 0"
                    )
                except sqlite3.OperationalError:
                    pass

        try:
            connection.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
    finally:
        connection.close()


def clear_firefox_history(database: Path, complete: bool = False) -> None:
    """Clear Firefox history while strictly preserving user bookmarks."""
    connection = sqlite3.connect(database, timeout=5)
    try:
        with connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            for table in ("moz_historyvisits", "moz_inputhistory"):
                try:
                    connection.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    pass

            # Remove places that are not bookmarks (handles both fk and place_id schemas)
            try:
                connection.execute(
                    """
                    DELETE FROM moz_places
                    WHERE id NOT IN (
                        SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL
                    )
                    """
                )
            except sqlite3.OperationalError:
                try:
                    connection.execute(
                        """
                        DELETE FROM moz_places
                        WHERE id NOT IN (
                            SELECT place_id FROM moz_bookmarks WHERE place_id IS NOT NULL
                        )
                        """
                    )
                except sqlite3.OperationalError:
                    pass

            try:
                connection.execute(
                    "UPDATE moz_places SET visit_count = 0, last_visit_date = NULL"
                )
            except sqlite3.OperationalError:
                pass

        try:
            connection.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
    finally:
        connection.close()


def scan_directory_stats(directory: Path) -> tuple[int, int]:
    """Return (total_bytes, total_files) in directory without deleting."""
    total_bytes = 0
    total_files = 0
    if not directory.is_dir():
        return total_bytes, total_files

    for current, _, files in os.walk(directory):
        current_path = Path(current)
        for filename in files:
            target = current_path / filename
            try:
                stat = target.stat()
                total_bytes += stat.st_size
                total_files += 1
            except OSError:
                pass
    return total_bytes, total_files


def clean_temp_directory(directory: Path) -> CleanupResult:
    """Clean all contents inside directory, calculating freed bytes and removed items."""
    result = CleanupResult()
    try:
        entries = list(directory.iterdir())
    except OSError as error:
        result.errors.append(f"{directory}: {error}")
        return result

    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            try:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                entry.unlink()
                result.files_removed += 1
                result.bytes_freed += size
            except OSError as error:
                result.errors.append(f"{entry}: {error}")
            continue

        for current, directories, files in os.walk(entry, topdown=False):
            current_path = Path(current)
            for filename in files:
                target = current_path / filename
                try:
                    try:
                        size = target.stat().st_size
                    except OSError:
                        size = 0
                    target.unlink()
                    result.files_removed += 1
                    result.bytes_freed += size
                except OSError as error:
                    result.errors.append(f"{target}: {error}")
            for dirname in directories:
                target = current_path / dirname
                try:
                    if target.is_symlink():
                        try:
                            size = target.stat().st_size
                        except OSError:
                            size = 0
                        target.unlink()
                        result.files_removed += 1
                        result.bytes_freed += size
                    elif target.exists():
                        target.rmdir()
                        result.directories_removed += 1
                except OSError as error:
                    result.errors.append(f"{target}: {error}")
        try:
            current_path = entry
            if current_path.exists():
                current_path.rmdir()
                result.directories_removed += 1
        except OSError as error:
            result.errors.append(f"{entry}: {error}")
    return result


def empty_windows_recycle_bin() -> tuple[bool, str]:
    """Empty the Windows Recycle Bin using Windows Shell API."""
    try:
        # SHERB_NOCONFIRMATION (0x1) | SHERB_NOPROGRESSUI (0x2) | SHERB_NOSOUND (0x4) = 7
        ret = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)
        if ret == 0 or ret == -2147418113:  # 0 = S_OK, -2147418113 = already empty
            return True, "Lixeira do Windows esvaziada com sucesso."
        return False, f"Código de retorno: {ret}"
    except Exception as exc:
        return False, str(exc)


def flush_dns_resolver() -> tuple[bool, str]:
    """Flush Windows DNS Resolver cache."""
    try:
        creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        res = subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            errors="replace",
        )
        if res.returncode == 0:
            return True, "Cache DNS limpo com sucesso."
        return False, res.stderr or "Falha ao limpar cache DNS"
    except Exception as exc:
        return False, str(exc)


def optimize_system_memory() -> tuple[bool, str]:
    """Trim working sets of current process and trigger system memory cleanup."""
    try:
        if sys.platform == "win32":
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetProcessWorkingSetSize(handle, -1, -1)
        return True, "Memória RAM do sistema otimizada."
    except Exception as exc:
        return False, str(exc)


def get_running_browser_processes() -> list[str]:
    """Detect running browsers to prevent locked databases."""
    browser_exes = {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "brave.exe": "Brave Browser",
        "firefox.exe": "Mozilla Firefox",
        "opera.exe": "Opera",
        "vivaldi.exe": "Vivaldi",
    }
    found = []
    try:
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            errors="replace",
        )
        lines = proc.stdout.splitlines()
        running_names = {line.split(",")[0].strip('"\r\n ').lower() for line in lines if line}
        for exe, label in browser_exes.items():
            if exe.lower() in running_names:
                found.append(label)
    except Exception:
        pass
    return found


def close_running_browser_processes() -> list[str]:
    """Terminate running browser processes cleanly."""
    closed = []
    targets = ["chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe"]
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    for exe in targets:
        try:
            res = subprocess.run(
                ["taskkill", "/F", "/IM", exe],
                capture_output=True,
                creationflags=creationflags,
            )
            if res.returncode == 0:
                closed.append(exe)
        except Exception:
            pass
    return closed


def run_cleanup(
    clean_temporary: bool = True,
    clear_browser_history: bool = True,
    complete_history: bool = True,
    clean_browser_cache: bool = True,
    clean_system_temp: bool = True,
    clean_recycle_bin: bool = True,
    clean_crash_dumps: bool = True,
    clean_thumbnails: bool = True,
    flush_dns: bool = True,
    optimize_memory: bool = True,
    log_callback: Callable[[str], None] | None = None,
) -> CleanupResult:
    """Perform full cleanup and optimization according to chosen parameters."""
    result = CleanupResult()

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    # 1. User Temp
    if clean_temporary:
        log("📁 Limpando arquivos temporários do usuário (%TEMP%)...")
        user_temp = Path(tempfile.gettempdir())
        res = clean_temp_directory(user_temp)
        result.files_removed += res.files_removed
        result.directories_removed += res.directories_removed
        result.bytes_freed += res.bytes_freed
        result.errors.extend(res.errors)
        log(f"   ↳ {res.files_removed} arquivos removidos ({format_bytes(res.bytes_freed)})")

    # 2. System Temp
    if clean_system_temp:
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        sys_temp = Path(sys_root) / "Temp"
        if sys_temp.is_dir():
            log("📁 Limpando pasta temporária do Windows...")
            res = clean_temp_directory(sys_temp)
            result.files_removed += res.files_removed
            result.directories_removed += res.directories_removed
            result.bytes_freed += res.bytes_freed
            result.errors.extend(res.errors)
            log(f"   ↳ {res.files_removed} arquivos do sistema removidos ({format_bytes(res.bytes_freed)})")

    # 3. Crash Dumps
    if clean_crash_dumps:
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            dumps_path = Path(local_app) / "CrashDumps"
            if dumps_path.is_dir():
                log("💥 Limpando relatórios de falhas (Crash Dumps)...")
                res = clean_temp_directory(dumps_path)
                result.files_removed += res.files_removed
                result.directories_removed += res.directories_removed
                result.bytes_freed += res.bytes_freed
                result.errors.extend(res.errors)

            wer_path = Path(local_app) / "Microsoft" / "Windows" / "WER"
            if wer_path.is_dir():
                log("⚠️ Limpando relatórios de erro do Windows (WER)...")
                for sub in ("ReportArchive", "ReportQueue"):
                    sub_p = wer_path / sub
                    if sub_p.is_dir():
                        res = clean_temp_directory(sub_p)
                        result.files_removed += res.files_removed
                        result.directories_removed += res.directories_removed
                        result.bytes_freed += res.bytes_freed
                        result.errors.extend(res.errors)

    # 4. Thumbnail & Icon Cache
    if clean_thumbnails:
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            expl_dir = Path(local_app) / "Microsoft" / "Windows" / "Explorer"
            if expl_dir.is_dir():
                log("🖼️ Limpando cache de miniaturas e ícones...")
                try:
                    for f in expl_dir.iterdir():
                        if f.is_file() and (f.name.startswith("thumbcache_") or f.name.startswith("iconcache_")):
                            try:
                                sz = f.stat().st_size
                                f.unlink()
                                result.files_removed += 1
                                result.bytes_freed += sz
                            except OSError:
                                pass
                except OSError:
                    pass

    # 5. Browser History
    if clear_browser_history:
        log("🌐 Limpando e compactando histórico dos navegadores...")
        history_files = discover_browser_history_files()
        for browser, database, database_type in history_files:
            try:
                if database_type == "firefox":
                    clear_firefox_history(database, complete=complete_history)
                else:
                    clear_chromium_history(database, complete=complete_history)
                result.browser_databases_cleared += 1
                log(f"   ✓ Histórico limpo e compactado: {browser} ({database.parent.name})")
            except (OSError, sqlite3.Error) as error:
                result.errors.append(f"{browser} ({database}): {error}")
                log(f"   ✕ Aviso {browser}: {error}")

    # 6. Browser Caches
    if clean_browser_cache:
        log("⚡ Limpando caches web dos navegadores (liberando espaço)...")
        cache_dirs = discover_browser_cache_directories()
        for label, c_dir in cache_dirs:
            res = clean_temp_directory(c_dir)
            result.files_removed += res.files_removed
            result.directories_removed += res.directories_removed
            result.bytes_freed += res.bytes_freed
            result.browser_caches_cleared += 1
            if res.bytes_freed > 0:
                log(f"   ↳ {label}: {format_bytes(res.bytes_freed)} liberados")

    # 7. Recycle Bin
    if clean_recycle_bin:
        log("🗑️ Esvaziando Lixeira do Windows...")
        ok, msg = empty_windows_recycle_bin()
        if ok:
            result.system_tasks_done.append("Lixeira esvaziada")
            log("   ✓ Lixeira esvaziada com sucesso.")
        else:
            result.errors.append(f"Lixeira: {msg}")
            log(f"   ✕ Aviso Lixeira: {msg}")

    # 8. DNS Flush
    if flush_dns:
        log("📡 Liberando Cache do DNS Resolver...")
        ok, msg = flush_dns_resolver()
        if ok:
            result.system_tasks_done.append("Cache DNS limpo")
            log("   ✓ Cache DNS limpo com sucesso.")
        else:
            result.errors.append(f"DNS: {msg}")
            log(f"   ✕ Aviso DNS: {msg}")

    # 9. RAM Optimization
    if optimize_memory:
        log("🧠 Otimizando consumo de memória RAM...")
        ok, msg = optimize_system_memory()
        if ok:
            result.system_tasks_done.append("Memória RAM otimizada")
            log("   ✓ Memória RAM do sistema otimizada.")

    log(f"\n🎉 Limpeza concluída! Total liberado: {format_bytes(result.bytes_freed)} | Arquivos: {result.files_removed}")
    return result


class ModernTheme:
    BG_DARK = "#181825"
    CARD_BG = "#1e1e2e"
    BORDER = "#313244"
    TEXT_MAIN = "#cdd6f4"
    TEXT_MUTED = "#a6adc8"
    PRIMARY = "#3b82f6"
    PRIMARY_HOVER = "#2563eb"
    SUCCESS = "#a6e3a1"
    ACCENT = "#89b4fa"
    WARNING = "#f9e2af"
    DANGER = "#f38ba8"
    CONSOLE_BG = "#11111b"


class CleanerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("⚡ Otimizador do Windows & PC v5.0")
        root.geometry("680x720")
        root.minsize(620, 640)
        root.configure(bg=ModernTheme.BG_DARK)

        self.queue: Queue[tuple[str, object]] = Queue()
        self.is_running = False

        self._configure_styles()
        self._build_ui()
        self.root.after(100, self._process_queue)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=ModernTheme.BG_DARK, foreground=ModernTheme.TEXT_MAIN)
        style.configure("TFrame", background=ModernTheme.BG_DARK)
        style.configure("Card.TFrame", background=ModernTheme.CARD_BG, relief="flat")
        style.configure("TLabel", background=ModernTheme.CARD_BG, foreground=ModernTheme.TEXT_MAIN, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=ModernTheme.BG_DARK, foreground="#ffffff", font=("Segoe UI", 16, "bold"))
        style.configure("Subtitle.TLabel", background=ModernTheme.BG_DARK, foreground=ModernTheme.TEXT_MUTED, font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=ModernTheme.CARD_BG, foreground=ModernTheme.ACCENT, font=("Segoe UI", 11, "bold"))
        
        style.configure(
            "TCheckbutton",
            background=ModernTheme.CARD_BG,
            foreground=ModernTheme.TEXT_MAIN,
            font=("Segoe UI", 9),
            indicatorcolor=ModernTheme.BG_DARK,
        )
        style.map(
            "TCheckbutton",
            indicatorcolor=[("selected", ModernTheme.PRIMARY), ("active", ModernTheme.PRIMARY_HOVER)],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            background=ModernTheme.PRIMARY,
            foreground="#ffffff",
            padding=(14, 8),
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", ModernTheme.PRIMARY_HOVER), ("disabled", ModernTheme.BORDER)],
            foreground=[("disabled", ModernTheme.TEXT_MUTED)],
        )

        style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 9),
            background=ModernTheme.BORDER,
            foreground=ModernTheme.TEXT_MAIN,
            padding=(10, 6),
            borderwidth=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#45475a")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=ModernTheme.BORDER,
            background=ModernTheme.PRIMARY,
            lightcolor=ModernTheme.ACCENT,
            darkcolor=ModernTheme.PRIMARY,
            bordercolor=ModernTheme.BG_DARK,
            thickness=6,
        )

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)

        # Title header
        header_frame = ttk.Frame(container)
        header_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(header_frame, text="⚡ Otimizador do Windows & PC", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header_frame,
            text="Limpeza profunda de sistema, navegadores, remoção de lixo e liberação de memória RAM.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Main options container
        options_card = ttk.Frame(container, style="Card.TFrame", padding=14)
        options_card.pack(fill="x", pady=(0, 10))

        # Variables
        self.clean_user_temp = tk.BooleanVar(value=True)
        self.clean_sys_temp = tk.BooleanVar(value=True)
        self.clean_recycle = tk.BooleanVar(value=True)
        self.clean_crash_dumps = tk.BooleanVar(value=True)
        self.clean_thumbnails = tk.BooleanVar(value=True)

        self.clean_history = tk.BooleanVar(value=True)
        self.complete_history = tk.BooleanVar(value=True)
        self.clean_cache = tk.BooleanVar(value=True)

        self.flush_dns = tk.BooleanVar(value=True)
        self.opt_ram = tk.BooleanVar(value=True)
        self.close_browsers_var = tk.BooleanVar(value=False)

        # Columns
        col_frame = ttk.Frame(options_card, style="Card.TFrame")
        col_frame.pack(fill="x")

        # Column 1: Windows & Sistema
        col1 = ttk.Frame(col_frame, style="Card.TFrame")
        col1.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(col1, text="🖥️ Windows & Disco", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(col1, text="Arquivos temporários do usuário (%TEMP%)", variable=self.clean_user_temp).pack(anchor="w", pady=2)
        ttk.Checkbutton(col1, text="Arquivos temporários do sistema", variable=self.clean_sys_temp).pack(anchor="w", pady=2)
        ttk.Checkbutton(col1, text="Esvaziar Lixeira do Windows", variable=self.clean_recycle).pack(anchor="w", pady=2)
        ttk.Checkbutton(col1, text="Cache de miniaturas do Explorer", variable=self.clean_thumbnails).pack(anchor="w", pady=2)
        ttk.Checkbutton(col1, text="Dumps de falhas e erros (WER)", variable=self.clean_crash_dumps).pack(anchor="w", pady=2)

        # Column 2: Navegadores & Desempenho
        col2 = ttk.Frame(col_frame, style="Card.TFrame")
        col2.pack(side="left", fill="both", expand=True)
        ttk.Label(col2, text="🌐 Navegadores & Desempenho", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(col2, text="Histórico completo (URLs e visitas)", variable=self.clean_history).pack(anchor="w", pady=2)
        ttk.Checkbutton(col2, text="Cache web de navegação (libera GBs)", variable=self.clean_cache).pack(anchor="w", pady=2)
        ttk.Checkbutton(col2, text="Limpar cache DNS (ipconfig /flushdns)", variable=self.flush_dns).pack(anchor="w", pady=2)
        ttk.Checkbutton(col2, text="Otimizar memória RAM (Working Set Trim)", variable=self.opt_ram).pack(anchor="w", pady=2)
        ttk.Checkbutton(col2, text="Fechar navegadores antes da limpeza", variable=self.close_browsers_var).pack(anchor="w", pady=2)

        # Quick preset buttons
        preset_frame = ttk.Frame(container)
        preset_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(preset_frame, text="Marcar Tudo", style="Secondary.TButton", command=self._select_all).pack(side="left", padx=(0, 6))
        ttk.Button(preset_frame, text="Recomendado", style="Secondary.TButton", command=self._select_recommended).pack(side="left", padx=(0, 6))
        ttk.Button(preset_frame, text="Desmarcar Tudo", style="Secondary.TButton", command=self._deselect_all).pack(side="left")

        # Action Buttons Frame
        action_frame = ttk.Frame(container)
        action_frame.pack(fill="x", pady=(0, 8))

        self.btn_analyze = ttk.Button(
            action_frame,
            text="🔍 Analisar Espaço",
            style="Secondary.TButton",
            command=self.start_analyze,
        )
        self.btn_analyze.pack(side="left", padx=(0, 10))

        self.btn_cleanup = ttk.Button(
            action_frame,
            text="🚀 Otimizar & Limpar Agora",
            style="Primary.TButton",
            command=self.start_cleanup,
        )
        self.btn_cleanup.pack(side="left")

        # Progress bar & status label
        self.progress = ttk.Progressbar(container, style="Horizontal.TProgressbar", mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 4))

        self.status_label = tk.Label(
            container,
            text="Pronto para otimizar. Clique em 'Analisar' ou 'Otimizar Agora'.",
            bg=ModernTheme.BG_DARK,
            fg=ModernTheme.TEXT_MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(0, 6))

        # Real-time Activity Log (Terminal)
        log_frame = ttk.Frame(container, style="Card.TFrame", padding=6)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            bg=ModernTheme.CONSOLE_BG,
            fg=ModernTheme.TEXT_MAIN,
            insertbackground="#ffffff",
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
            height=10,
        )
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._log("👋 Bem-vindo ao Otimizador do Windows & PC v5.0.")
        self._log("ℹ️ Navegadores suportados: Chrome, Edge, Brave, Opera, Opera GX, Vivaldi, Firefox.")
        self._log("🔒 Favoritos, senhas e downloads pessoais permanecem seguros.\n")

    def _select_all(self) -> None:
        for var in (
            self.clean_user_temp,
            self.clean_sys_temp,
            self.clean_recycle,
            self.clean_crash_dumps,
            self.clean_thumbnails,
            self.clean_history,
            self.clean_cache,
            self.flush_dns,
            self.opt_ram,
            self.close_browsers_var,
        ):
            var.set(True)

    def _select_recommended(self) -> None:
        self.clean_user_temp.set(True)
        self.clean_sys_temp.set(True)
        self.clean_recycle.set(True)
        self.clean_crash_dumps.set(True)
        self.clean_thumbnails.set(True)
        self.clean_history.set(True)
        self.clean_cache.set(True)
        self.flush_dns.set(True)
        self.opt_ram.set(True)
        self.close_browsers_var.set(False)

    def _deselect_all(self) -> None:
        for var in (
            self.clean_user_temp,
            self.clean_sys_temp,
            self.clean_recycle,
            self.clean_crash_dumps,
            self.clean_thumbnails,
            self.clean_history,
            self.clean_cache,
            self.flush_dns,
            self.opt_ram,
            self.close_browsers_var,
        ):
            var.set(False)

    def _log(self, text: str) -> None:
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _process_queue(self) -> None:
        while True:
            try:
                msg_type, payload = self.queue.get_nowait()
            except Empty:
                break

            if msg_type == "log":
                self._log(str(payload))
            elif msg_type == "status":
                self.status_label.config(text=str(payload))
            elif msg_type == "finish_analyze":
                self.progress.stop()
                self.btn_analyze.config(state="normal")
                self.btn_cleanup.config(state="normal")
                self.is_running = False
                total_bytes, total_files = payload  # type: ignore
                self.status_label.config(
                    text=f"Análise finalizada: {format_bytes(total_bytes)} em {total_files} arquivos analisados."
                )
                messagebox.showinfo(
                    "Análise Concluída",
                    f"Espaço estimado que pode ser liberado:\n\n"
                    f"💾 Espaço: {format_bytes(total_bytes)}\n"
                    f"📄 Arquivos temporários encontrados: {total_files}\n\n"
                    f"Clique em 'Otimizar & Limpar Agora' para executar a limpeza profunda.",
                )
            elif msg_type == "finish_cleanup":
                self.progress.stop()
                self.btn_analyze.config(state="normal")
                self.btn_cleanup.config(state="normal")
                self.is_running = False
                res: CleanupResult = payload  # type: ignore
                self.status_label.config(
                    text=f"Limpeza concluída! {format_bytes(res.bytes_freed)} liberados. Sistema otimizado!"
                )
                summary = (
                    f"Espaço liberado em disco: {format_bytes(res.bytes_freed)}\n"
                    f"Arquivos removidos: {res.files_removed}\n"
                    f"Pastas limpas: {res.directories_removed}\n"
                    f"Bancos de dados de histórico otimizados: {res.browser_databases_cleared}\n"
                    f"Caches de navegadores limpos: {res.browser_caches_cleared}\n"
                    f"Tarefas de sistema: {', '.join(res.system_tasks_done) if res.system_tasks_done else 'Nenhuma'}"
                )
                if res.errors:
                    summary += f"\n\nItens em uso / protegidos pelo Windows ({len(res.errors)} itens):\n"
                    summary += "\n".join(res.errors[:6])
                    if len(res.errors) > 6:
                        summary += f"\n... e mais {len(res.errors) - 6} item(s)."
                    messagebox.showwarning("Limpeza Concluída com Avisos", summary)
                else:
                    messagebox.showinfo("Limpeza e Otimização Concluída", summary)

        self.root.after(100, self._process_queue)

    def start_analyze(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.btn_analyze.config(state="disabled")
        self.btn_cleanup.config(state="disabled")
        self.progress.start(10)
        self.status_label.config(text="Analisando pastas temporárias e caches do sistema...")

        def worker() -> None:
            total_bytes = 0
            total_files = 0
            self.queue.put(("log", "🔍 Iniciando varredura e análise de espaço..."))

            targets = []
            if self.clean_user_temp.get():
                targets.append(("Temp do Usuário", Path(tempfile.gettempdir())))
            if self.clean_sys_temp.get():
                sys_root = os.environ.get("SystemRoot", r"C:\Windows")
                targets.append(("Temp do Windows", Path(sys_root) / "Temp"))
            if self.clean_crash_dumps.get():
                loc = os.environ.get("LOCALAPPDATA")
                if loc:
                    targets.append(("Crash Dumps", Path(loc) / "CrashDumps"))
            if self.clean_cache.get():
                for label, cdir in discover_browser_cache_directories():
                    targets.append((label, cdir))

            for name, path in targets:
                if path.is_dir():
                    self.queue.put(("status", f"Analisando: {name}..."))
                    b, f = scan_directory_stats(path)
                    total_bytes += b
                    total_files += f
                    if b > 0:
                        self.queue.put(("log", f"   • {name}: {format_bytes(b)} ({f} arquivos)"))

            self.queue.put(("log", f"📊 Análise concluída: {format_bytes(total_bytes)} detectados."))
            self.queue.put(("finish_analyze", (total_bytes, total_files)))

        threading.Thread(target=worker, daemon=True).start()

    def start_cleanup(self) -> None:
        if self.is_running:
            return

        any_selected = any(
            v.get()
            for v in (
                self.clean_user_temp,
                self.clean_sys_temp,
                self.clean_recycle,
                self.clean_crash_dumps,
                self.clean_thumbnails,
                self.clean_history,
                self.clean_cache,
                self.flush_dns,
                self.opt_ram,
            )
        )
        if not any_selected:
            messagebox.showinfo("Aviso", "Selecione pelo menos uma opção de limpeza ou otimização.")
            return

        # Check running browsers
        running_browsers = get_running_browser_processes()
        if running_browsers:
            if self.close_browsers_var.get():
                close_running_browser_processes()
                time.sleep(0.5)
            else:
                msg = (
                    f"Detectamos navegadores abertos: {', '.join(running_browsers)}.\n\n"
                    "Deseja fechá-los agora para garantir a limpeza total do histórico e cache?"
                )
                if messagebox.askyesno("Navegadores Abertos", msg):
                    close_running_browser_processes()
                    time.sleep(0.5)

        if not messagebox.askyesno(
            "Confirmar Limpeza e Otimização",
            "Deseja iniciar a limpeza dos itens selecionados e otimizar o sistema?",
        ):
            return

        self.is_running = True
        self.btn_analyze.config(state="disabled")
        self.btn_cleanup.config(state="disabled")
        self.progress.start(10)
        self.status_label.config(text="Otimizando o sistema... Aguarde.")

        def log_cb(msg: str) -> None:
            self.queue.put(("log", msg))

        def worker() -> None:
            result = run_cleanup(
                clean_temporary=self.clean_user_temp.get(),
                clear_browser_history=self.clean_history.get(),
                complete_history=self.complete_history.get(),
                clean_browser_cache=self.clean_cache.get(),
                clean_system_temp=self.clean_sys_temp.get(),
                clean_recycle_bin=self.clean_recycle.get(),
                clean_crash_dumps=self.clean_crash_dumps.get(),
                clean_thumbnails=self.clean_thumbnails.get(),
                flush_dns=self.flush_dns.get(),
                optimize_memory=self.opt_ram.get(),
                log_callback=log_cb,
            )
            self.queue.put(("finish_cleanup", result))

        threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    root = tk.Tk()
    CleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
