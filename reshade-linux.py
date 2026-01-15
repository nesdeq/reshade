#!/usr/bin/env python3
"""
ReShade Linux Installer - A modern CLI tool for installing ReShade on Linux.

Copyright (C) 2021-2024 kevinlekiller, modernized by contributors

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later version.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# Constants
# =============================================================================

RESHADE_URLS = ("https://reshade.me", "http://static.reshade.me")

SHADER_REPOS: list[tuple[str, str, Optional[str]]] = [
    ("https://github.com/crosire/reshade-shaders", "reshade-shaders", "slim"),
    ("https://github.com/CeeJayDK/SweetFX", "sweetfx-shaders", None),
    ("https://github.com/martymcmodding/qUINT", "qUINT-shaders", None),
    ("https://github.com/BlueSkyDefender/AstrayFX", "astrayfx-shaders", None),
    ("https://github.com/prod80/prod80-ReShade-Repository", "prod80-shaders", None),
]

DLL_OPTIONS = (
    ("dxgi", "DirectX 10/11/12"),
    ("d3d9", "DirectX 9"),
    ("d3d11", "DirectX 11 alternative"),
    ("d3d10", "DirectX 10"),
    ("opengl32", "OpenGL"),
    ("d3d8", "DirectX 8"),
    ("ddraw", "DirectDraw"),
    ("dinput8", "DirectInput 8"),
)

RESHADE_LINKS = (
    "d3d8.dll", "d3d9.dll", "d3d10.dll", "d3d11.dll", "dxgi.dll",
    "ddraw.dll", "dinput8.dll", "opengl32.dll", "d3dcompiler_47.dll",
    "ReShade.ini", "ReShade_shaders", "ReShade32.json", "ReShade64.json",
)

EXE_BLACKLIST = frozenset((
    "unins", "setup", "install", "crash", "report", "launcher", "updater",
    "vc_redist", "dxsetup", "dotnet", "directx", "easyanticheat", "battleye",
    "redist", "vcredist", "physx",
))

SHADER_EXTENSIONS = frozenset((".fx", ".fxh"))
TEXTURE_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".dds", ".bmp", ".tga"))

D3DCOMPILER_HASHES = {
    32: "d6edb4ff0a713f417ebd19baedfe07527c6e45e84a6c73ed8c66a33377cc0aca",
    64: "721977f36c008af2b637aedd3f1b529f3cfed6feb10f68ebe17469acb1934986",
}

REQUIRED_PACKAGES = ("rich", "questionary", "requests", "pefile")
REQUIRED_TOOLS = ("7z", "git")


# =============================================================================
# Dependency Management
# =============================================================================

def check_python_dependencies() -> list[str]:
    """Return list of missing Python packages."""
    missing = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def check_system_tools() -> list[str]:
    """Return list of missing system tools."""
    return [t for t in REQUIRED_TOOLS if shutil.which(t) is None]


def ensure_dependencies() -> None:
    """Check dependencies and exit with instructions if missing."""
    missing_pkgs = check_python_dependencies()
    if missing_pkgs:
        print(f"Missing Python packages: {', '.join(missing_pkgs)}")
        print("\nPlease install them:")
        print(f"  pip install {' '.join(missing_pkgs)}")
        sys.exit(1)

    missing_tools = check_system_tools()
    if missing_tools:
        print(f"Missing system tools: {', '.join(missing_tools)}")
        print("\nPlease install them using your package manager.")
        sys.exit(1)


# Check dependencies before importing optional packages
ensure_dependencies()

# Now safe to import
import pefile
import questionary
import requests
from questionary import Style
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.text import Text

console = Console()

QUESTIONARY_STYLE = Style([
    ("qmark", "fg:cyan bold"),
    ("question", "fg:white bold"),
    ("answer", "fg:green bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:green"),
    ("separator", "fg:gray"),
    ("instruction", "fg:gray italic"),
])


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GameInfo:
    """Represents a detected or configured game."""
    name: str
    path: Path
    exe_files: list[Path] = field(default_factory=list)
    architecture: int = 64
    detected_api: str = "dx11"
    dll_override: str = "dxgi"
    install_path: Optional[Path] = None
    selected_exe: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.install_path is None:
            self.install_path = self.path

    def __str__(self) -> str:
        return f"{self.name} ({self.detected_api.upper()}, {self.architecture}-bit)"

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "name": self.name,
            "path": str(self.path),
            "architecture": self.architecture,
            "detected_api": self.detected_api,
            "dll_override": self.dll_override,
            "install_path": str(self.install_path) if self.install_path else None,
            "selected_exe": str(self.selected_exe) if self.selected_exe else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GameInfo:
        """Deserialize from JSON storage."""
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            architecture=data.get("architecture", 64),
            detected_api=data.get("detected_api", "dx11"),
            dll_override=data.get("dll_override", "dxgi"),
            install_path=Path(data["install_path"]) if data.get("install_path") else None,
            selected_exe=Path(data["selected_exe"]) if data.get("selected_exe") else None,
        )


@dataclass
class Config:
    """Application configuration."""
    main_path: Path = field(default_factory=lambda: Path.home() / ".local/reshade")
    reshade_version: str = "latest"
    addon_support: bool = False
    merge_shaders: bool = True
    global_ini: str = "ReShade.ini"

    @property
    def reshade_path(self) -> Path:
        return self.main_path / "reshade"

    @property
    def shaders_path(self) -> Path:
        return self.main_path / "ReShade_shaders"

    @property
    def merged_path(self) -> Path:
        return self.shaders_path / "Merged"

    @property
    def external_shaders_path(self) -> Path:
        return self.main_path / "External_shaders"

    @property
    def games_config_path(self) -> Path:
        return self.main_path / "games.json"


# =============================================================================
# Games Configuration Manager
# =============================================================================

class GamesConfigManager:
    """Manages per-game configuration persistence."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load games config from disk."""
        if self.config_path.exists():
            try:
                self._cache = json.loads(self.config_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        """Save games config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self._cache, indent=2))

    def _game_key(self, game_path: Path) -> str:
        """Generate unique key for a game based on its path."""
        return str(game_path.resolve())

    def get(self, game_path: Path) -> Optional[GameInfo]:
        """Get saved configuration for a game."""
        key = self._game_key(game_path)
        if key in self._cache:
            try:
                return GameInfo.from_dict(self._cache[key])
            except (KeyError, TypeError):
                return None
        return None

    def save(self, game: GameInfo) -> None:
        """Save game configuration."""
        key = self._game_key(game.path)
        self._cache[key] = game.to_dict()
        self._save()

    def remove(self, game_path: Path) -> None:
        """Remove game configuration."""
        key = self._game_key(game_path)
        if key in self._cache:
            del self._cache[key]
            self._save()

    def list_all(self) -> list[GameInfo]:
        """List all saved game configurations."""
        games = []
        for data in self._cache.values():
            try:
                games.append(GameInfo.from_dict(data))
            except (KeyError, TypeError):
                continue
        return games


# =============================================================================
# Symlink Utilities
# =============================================================================

def safe_symlink(source: Path, target: Path, backup: bool = True) -> None:
    """Create a symlink, handling existing files/links."""
    if target.is_symlink():
        target.unlink()
    elif target.exists() and backup:
        backup_path = target.with_suffix(target.suffix + ".backup")
        shutil.move(str(target), str(backup_path))
    elif target.exists():
        target.unlink()
    target.symlink_to(source.resolve())


def safe_unlink(path: Path) -> bool:
    """Remove a symlink if it exists. Returns True if removed."""
    if path.is_symlink():
        path.unlink()
        return True
    return False


# =============================================================================
# Executable Analysis
# =============================================================================

def analyze_executable(exe_path: Path) -> tuple[int, str, str]:
    """
    Analyze an executable to determine architecture and graphics API.

    Returns: (architecture, api, dll_override)
    """
    arch = 64
    api = "dx11"
    dll = "dxgi"

    try:
        pe = pefile.PE(str(exe_path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )

        # Check architecture
        if pe.FILE_HEADER.Machine == pefile.MACHINE_TYPE["IMAGE_FILE_MACHINE_I386"]:
            arch = 32

        # Check imported DLLs for graphics API
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            imports = {
                entry.dll.decode("utf-8", errors="ignore").lower()
                for entry in pe.DIRECTORY_ENTRY_IMPORT
            }

            if "d3d12.dll" in imports:
                api, dll = "dx12", "dxgi"
            elif "d3d11.dll" in imports or "dxgi.dll" in imports:
                api, dll = "dx11", "dxgi"
            elif "d3d10.dll" in imports or "d3d10_1.dll" in imports:
                api, dll = "dx10", "d3d10"
            elif "d3d9.dll" in imports:
                api, dll = "dx9", "d3d9"
            elif "opengl32.dll" in imports:
                api, dll = "opengl", "opengl32"
            elif "d3d8.dll" in imports:
                api, dll = "dx8", "d3d8"

        pe.close()

    except Exception:
        # Fallback: check PE header manually for architecture
        try:
            with open(exe_path, "rb") as f:
                f.seek(0x3C)
                pe_offset = struct.unpack("<I", f.read(4))[0]
                f.seek(pe_offset + 4)
                machine = struct.unpack("<H", f.read(2))[0]
                if machine == 0x14C:  # IMAGE_FILE_MACHINE_I386
                    arch = 32
                    dll = "d3d9"
        except Exception:
            pass

    return arch, api, dll


def is_game_executable(exe_path: Path) -> bool:
    """Check if an executable is likely a game (not a tool/installer)."""
    name_lower = exe_path.name.lower()
    return not any(blacklisted in name_lower for blacklisted in EXE_BLACKLIST)


# =============================================================================
# Steam Library Scanner
# =============================================================================

class SteamScanner:
    """Scans Steam libraries for installed games."""

    def __init__(self) -> None:
        self.library_paths: list[Path] = []

    def find_libraries(self) -> list[Path]:
        """Find all Steam library folders."""
        libraries: set[Path] = set()

        # Parse libraryfolders.vdf
        vdf_locations = [
            Path.home() / ".local/share/Steam/steamapps/libraryfolders.vdf",
            Path.home() / ".steam/steam/steamapps/libraryfolders.vdf",
        ]

        for vdf_path in vdf_locations:
            if vdf_path.exists():
                try:
                    content = vdf_path.read_text()
                    for path_match in re.findall(r'"path"\s+"([^"]+)"', content):
                        lib_path = Path(path_match) / "steamapps/common"
                        if lib_path.is_dir():
                            libraries.add(lib_path)
                except OSError:
                    continue

        # Check default locations
        default_paths = [
            Path.home() / ".local/share/Steam/steamapps/common",
            Path.home() / ".steam/steam/steamapps/common",
        ]
        for path in default_paths:
            if path.is_dir():
                libraries.add(path)

        # Check mounted drives
        mnt = Path("/mnt")
        if mnt.is_dir():
            for mount in mnt.iterdir():
                steam_common = mount / "SteamLibrary/steamapps/common"
                if steam_common.is_dir():
                    libraries.add(steam_common)

        self.library_paths = sorted(libraries)
        return self.library_paths

    def scan_for_games(self) -> list[GameInfo]:
        """Scan all Steam libraries for games with executables."""
        if not self.library_paths:
            self.find_libraries()

        games: list[GameInfo] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Scanning for games..."),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task("Scanning", total=None)

            for lib_path in self.library_paths:
                for game_dir in lib_path.iterdir():
                    if not game_dir.is_dir():
                        continue

                    exe_files = [
                        exe for exe in game_dir.rglob("*.exe")
                        if is_game_executable(exe)
                    ]

                    if exe_files:
                        games.append(GameInfo(
                            name=game_dir.name,
                            path=game_dir,
                            exe_files=exe_files,
                        ))

        return sorted(games, key=lambda g: g.name.lower())


# =============================================================================
# ReShade Installer Core
# =============================================================================

class ReShadeInstaller:
    """Main installer class for ReShade operations."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ReShade-Linux-Installer/2.0"})
        self.games_config = GamesConfigManager(self.config.games_config_path)
        self.steam_scanner = SteamScanner()

    def setup_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            self.config.main_path,
            self.config.reshade_path,
            self.config.shaders_path,
            self.config.merged_path / "Shaders",
            self.config.merged_path / "Textures",
            self.config.external_shaders_path,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def get_latest_reshade_version(self) -> tuple[str, str]:
        """Fetch the latest ReShade version and download URL."""
        pattern_suffix = r"_Addon" if self.config.addon_support else ""
        pattern = rf"/downloads/ReShade_Setup_([0-9.]+{pattern_suffix})\.exe"

        for base_url in RESHADE_URLS:
            try:
                response = self.session.get(base_url, timeout=15)
                response.raise_for_status()

                match = re.search(pattern, response.text)
                if match:
                    version = match.group(1)
                    download_url = f"{base_url}/downloads/ReShade_Setup_{version}.exe"
                    return version, download_url

            except requests.RequestException:
                continue

        raise RuntimeError("Failed to fetch ReShade version from any source")

    def download_reshade(self, version: str, url: str) -> None:
        """Download and extract ReShade."""
        version_path = self.config.reshade_path / version

        if version_path.exists() and (version_path / "ReShade64.dll").exists():
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            exe_path = tmp_path / f"ReShade_Setup_{version}.exe"

            with Progress(
                SpinnerColumn(),
                TextColumn("[cyan]Downloading ReShade..."),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Download", total=100)

                response = self.session.get(url, stream=True)
                total = int(response.headers.get("content-length", 0))

                with open(exe_path, "wb") as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            progress.update(task, completed=int(downloaded * 100 / total))

            console.print("[cyan]Extracting ReShade...")
            version_path.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["7z", "e", "-y", str(exe_path), f"-o{version_path}"],
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to extract ReShade: {result.stderr.decode()}")

        # Update latest symlink
        latest_link = self.config.reshade_path / "latest"
        safe_unlink(latest_link)
        latest_link.symlink_to(version_path)

        # Save version info
        (self.config.main_path / "LVERS").write_text(version)

    def download_d3dcompiler(self, arch: int) -> None:
        """Download d3dcompiler_47.dll from Firefox installer."""
        dll_path = self.config.main_path / f"d3dcompiler_47.dll.{arch}"

        if dll_path.exists():
            return

        console.print(f"[cyan]Downloading d3dcompiler_47.dll ({arch}-bit)...")

        ff_url = (
            f"https://download-installer.cdn.mozilla.net/pub/firefox/releases/"
            f"62.0.3/win{arch}/ach/Firefox%20Setup%2062.0.3.exe"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ff_exe = tmp_path / "firefox.exe"

            response = self.session.get(ff_url)
            ff_exe.write_bytes(response.content)

            # Verify hash
            file_hash = hashlib.sha256(ff_exe.read_bytes()).hexdigest()
            if file_hash != D3DCOMPILER_HASHES[arch]:
                raise RuntimeError("Firefox integrity check failed")

            # Extract
            subprocess.run(
                ["7z", "e", "-y", str(ff_exe), f"-o{tmp_path}"],
                capture_output=True,
            )

            extracted_dll = tmp_path / "d3dcompiler_47.dll"
            if extracted_dll.exists():
                shutil.copy(extracted_dll, dll_path)
            else:
                raise RuntimeError("d3dcompiler_47.dll not found in Firefox archive")

    def clone_or_update_repo(self, url: str, name: str, branch: Optional[str] = None) -> bool:
        """Clone or update a git repository."""
        repo_path = self.config.shaders_path / name

        try:
            if repo_path.exists():
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "pull"],
                    capture_output=True,
                    timeout=60,
                )
                return result.returncode == 0
            else:
                cmd = ["git", "clone", "--depth", "1"]
                if branch:
                    cmd.extend(["--branch", branch])
                cmd.extend([url, str(repo_path)])

                result = subprocess.run(cmd, capture_output=True, timeout=120)
                return result.returncode == 0

        except (subprocess.TimeoutExpired, OSError):
            return False

    def download_all_shaders(self, repos: Optional[list[tuple]] = None) -> None:
        """Download all shader repositories."""
        repos = repos or SHADER_REPOS

        console.print("\n[bold cyan]Downloading shader repositories...[/]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Shaders", total=len(repos))

            for url, name, branch in repos:
                progress.update(task, description=f"[cyan]{name}...")
                self.clone_or_update_repo(url, name, branch)
                progress.update(task, advance=1)

        if self.config.merge_shaders:
            self.merge_shaders()

    def merge_shaders(self) -> None:
        """Merge all shader and texture files into the Merged directory."""
        console.print("[cyan]Merging shaders...")

        merged_shaders = self.config.merged_path / "Shaders"
        merged_textures = self.config.merged_path / "Textures"

        # Clear existing symlinks
        for directory in (merged_shaders, merged_textures):
            if directory.exists():
                for item in directory.iterdir():
                    if item.is_symlink():
                        item.unlink()

        seen_files: set[str] = set()

        def link_file(source: Path, target_dir: Path) -> bool:
            """Link a file if not already seen."""
            if source.name in seen_files:
                return False
            seen_files.add(source.name)
            target = target_dir / source.name
            if not target.exists():
                target.symlink_to(source.resolve())
                return True
            return False

        # Merge from shader repositories
        for repo_dir in self.config.shaders_path.iterdir():
            if repo_dir.name == "Merged" or not repo_dir.is_dir():
                continue

            for shaders_dir in repo_dir.rglob("Shaders"):
                if shaders_dir.is_dir():
                    for shader_file in shaders_dir.iterdir():
                        if shader_file.is_file():
                            link_file(shader_file, merged_shaders)

            for textures_dir in repo_dir.rglob("Textures"):
                if textures_dir.is_dir():
                    for texture_file in textures_dir.iterdir():
                        if texture_file.is_file():
                            link_file(texture_file, merged_textures)

        # Merge from External_shaders directory
        external = self.config.external_shaders_path
        if external.exists():
            # Check subdirectories
            ext_shaders = external / "Shaders"
            ext_textures = external / "Textures"

            if ext_shaders.exists():
                for f in ext_shaders.iterdir():
                    if f.is_file():
                        link_file(f, merged_shaders)

            if ext_textures.exists():
                for f in ext_textures.iterdir():
                    if f.is_file():
                        link_file(f, merged_textures)

            # Loose files in External_shaders root
            for item in external.iterdir():
                if not item.is_file():
                    continue
                suffix = item.suffix.lower()
                if suffix in SHADER_EXTENSIONS:
                    link_file(item, merged_shaders)
                elif suffix in TEXTURE_EXTENSIONS:
                    link_file(item, merged_textures)

        console.print(f"[green]Merged {len(seen_files)} shader/texture files[/]")

    def create_reshade_ini(self) -> None:
        """Create default ReShade.ini configuration."""
        ini_path = self.config.main_path / self.config.global_ini

        if ini_path.exists():
            return

        # Build Windows-style paths for Wine
        user = os.environ.get("USER", "user")
        relative_path = str(self.config.main_path).replace(str(Path.home()), "").lstrip("/")
        wine_path = relative_path.replace("/", "\\\\")

        shaders_path = f"Z:\\\\home\\\\{user}\\\\{wine_path}\\\\ReShade_shaders\\\\Merged\\\\Shaders"
        textures_path = f"Z:\\\\home\\\\{user}\\\\{wine_path}\\\\ReShade_shaders\\\\Merged\\\\Textures"

        ini_content = f"""[DEPTH]
DepthCopyAtClearIndex=0
DepthCopyBeforeClears=0
UseAspectRatioHeuristics=1

[GENERAL]
EffectSearchPaths=,{shaders_path}
IntermediateCachePath=C:\\\\users\\\\steamuser\\\\Temp
PerformanceMode=0
PreprocessorDefinitions=
PresetPath=.\\\\ReShadePreset.ini
PresetTransitionDelay=1000
SkipLoadingDisabledEffects=0
TextureSearchPaths=,{textures_path}

[INPUT]
ForceShortcutModifiers=1
InputProcessing=2
KeyEffects=0,0,0,0
KeyNextPreset=0,0,0,0
KeyOverlay=36,0,0,0
KeyPerformanceMode=0,0,0,0
KeyPreviousPreset=0,0,0,0
KeyReload=0,0,0,0
KeyScreenshot=44,0,0,0

[OVERLAY]
ClockFormat=0
FPSPosition=1
NoFontScaling=1
SaveWindowState=0
ShowClock=0
ShowForceLoadEffectsButton=1
ShowFPS=0
ShowFrameTime=0
ShowScreenshotMessage=1
TutorialProgress=4
VariableListHeight=300.000000
VariableListUseTabs=0

[SCREENSHOT]
ClearAlpha=1
FileFormat=1
FileNamingFormat=0
JPEGQuality=90
SaveBeforeShot=0
SaveOverlayShot=0
SavePath=
SavePresetFile=0

[STYLE]
Alpha=1.000000
ChildRounding=0.000000
ColFPSText=1.000000,1.000000,0.784314,1.000000
EditorFont=ProggyClean.ttf
EditorFontSize=13
EditorStyleIndex=0
Font=ProggyClean.ttf
FontSize=13
FPSScale=1.000000
FrameRounding=0.000000
GrabRounding=0.000000
PopupRounding=0.000000
ScrollbarRounding=0.000000
StyleIndex=2
TabRounding=4.000000
WindowRounding=0.000000
"""
        ini_path.write_text(ini_content)

    def get_current_version(self) -> str:
        """Get the current ReShade version string."""
        version = self.config.reshade_version
        if version == "latest":
            lvers_path = self.config.main_path / "LVERS"
            if lvers_path.exists():
                version = lvers_path.read_text().strip()
        return version

    def install_to_game(self, game: GameInfo) -> str:
        """Install ReShade to a game directory."""
        version = self.get_current_version()
        reshade_dll = self.config.reshade_path / version / f"ReShade{game.architecture}.dll"

        if not reshade_dll.exists():
            raise FileNotFoundError(f"ReShade DLL not found: {reshade_dll}")

        install_dir = game.install_path

        # Link ReShade DLL
        target_dll = install_dir / f"{game.dll_override}.dll"
        safe_symlink(reshade_dll, target_dll)
        console.print(f"[green]Linked ReShade{game.architecture}.dll -> {game.dll_override}.dll[/]")

        # Link d3dcompiler_47.dll
        self.download_d3dcompiler(game.architecture)
        d3d_src = self.config.main_path / f"d3dcompiler_47.dll.{game.architecture}"
        d3d_dst = install_dir / "d3dcompiler_47.dll"
        safe_symlink(d3d_src, d3d_dst, backup=False)
        console.print("[green]Linked d3dcompiler_47.dll[/]")

        # Link shaders directory
        shaders_link = install_dir / "ReShade_shaders"
        safe_symlink(self.config.shaders_path, shaders_link, backup=False)
        console.print("[green]Linked ReShade_shaders[/]")

        # Link config
        if self.config.global_ini:
            ini_src = self.config.main_path / self.config.global_ini
            ini_dst = install_dir / self.config.global_ini
            if ini_src.exists():
                safe_symlink(ini_src, ini_dst, backup=False)
                console.print(f"[green]Linked {self.config.global_ini}[/]")

        # Save game configuration
        self.games_config.save(game)

        return game.dll_override

    def uninstall_from_game(self, game_path: Path) -> list[str]:
        """Uninstall ReShade from a game directory."""
        removed = []
        for link_name in RESHADE_LINKS:
            link_path = game_path / link_name
            if safe_unlink(link_path):
                removed.append(link_name)
        return removed


# =============================================================================
# UI Components
# =============================================================================

def display_banner() -> None:
    """Display application banner."""
    banner = """
 ____      ____  _               _        _     _
|  _ \\ ___/ ___|| |__   __ _  __| | ___  | |   (_)_ __  _   ___  __
| |_) / _ \\___ \\| '_ \\ / _` |/ _` |/ _ \\ | |   | | '_ \\| | | \\ \\/ /
|  _ <  __/___) | | | | (_| | (_| |  __/ | |___| | | | | |_| |>  <
|_| \\_\\___|____/|_| |_|\\__,_|\\__,_|\\___| |_____|_|_| |_|\\__,_/_/\\_\\"""

    console.print(Panel(
        Text(banner, style="bold cyan", justify="center"),
        subtitle="[dim]Modern ReShade installer for Linux[/]",
        box=box.DOUBLE,
    ))


def ask_select(message: str, choices: list, allow_none: bool = True):
    """Wrapper for questionary select with consistent styling."""
    return questionary.select(message, choices=choices, style=QUESTIONARY_STYLE).ask()


def ask_confirm(message: str, default: bool = True) -> bool:
    """Wrapper for questionary confirm with consistent styling."""
    result = questionary.confirm(message, default=default, style=QUESTIONARY_STYLE).ask()
    return result if result is not None else False


def ask_path(message: str) -> Optional[str]:
    """Wrapper for questionary path with consistent styling."""
    return questionary.path(message, style=QUESTIONARY_STYLE).ask()


# =============================================================================
# UI Flows
# =============================================================================

def select_game(games: list[GameInfo]) -> Optional[GameInfo | str]:
    """Interactive game selection."""
    if not games:
        console.print("[yellow]No games found![/]")
        return None

    choices = [
        questionary.Choice(title=g.name, value=g) for g in games
    ]
    choices.append(questionary.Choice(title="[Browse manually...]", value="manual"))
    choices.append(questionary.Choice(title="[Cancel]", value=None))

    return ask_select("Select a game:", choices)


def browse_for_game() -> Optional[GameInfo]:
    """Let user browse for a game directory manually."""
    path_str = ask_path("Enter path to game directory or exe file:")

    if not path_str:
        return None

    path = Path(path_str).expanduser().resolve()

    if not path.exists():
        console.print("[red]Path does not exist![/]")
        return None

    if path.is_file() and path.suffix.lower() == ".exe":
        install_path = path.parent
        exe_files = [path]
        name = path.parent.name
    else:
        install_path = path
        exe_files = [
            exe for exe in path.glob("*.exe")
            if is_game_executable(exe)
        ]
        name = path.name
        if not exe_files:
            console.print("[yellow]No .exe files found in directory[/]")
            if not ask_confirm("Continue anyway?"):
                return None

    return GameInfo(
        name=name,
        path=path,
        exe_files=exe_files,
        install_path=install_path,
    )


def select_exe_for_analysis(game: GameInfo, installer: ReShadeInstaller) -> GameInfo:
    """Let user select which exe to analyze for API detection."""
    # Check for saved configuration
    saved_config = installer.games_config.get(game.path)
    if saved_config and saved_config.selected_exe:
        exe_path = saved_config.selected_exe
        if exe_path.exists():
            console.print(f"\n[dim]Using saved executable: {exe_path.name}[/]")
            game.selected_exe = exe_path
            game.architecture = saved_config.architecture
            game.detected_api = saved_config.detected_api
            game.dll_override = saved_config.dll_override
            game.install_path = saved_config.install_path or exe_path.parent
            console.print(f"[green]Saved config: {game.detected_api.upper()}, {game.architecture}-bit -> {game.dll_override}.dll[/]")
            return game

    if len(game.exe_files) == 1:
        exe = game.exe_files[0]
    elif len(game.exe_files) == 0:
        console.print("[yellow]No executables found. Using manual configuration.[/]")
        return game
    else:
        console.print(f"\n[cyan]Found {len(game.exe_files)} executables in {game.name}[/]")

        # Show limited choices
        exe_choices = [
            questionary.Choice(
                title=str(e.relative_to(game.path)) if game.path in e.parents else e.name,
                value=e,
            )
            for e in game.exe_files[:20]
        ]

        exe = ask_select("Select the main game executable:", exe_choices)

    if exe:
        arch, api, dll = analyze_executable(exe)
        game.architecture = arch
        game.detected_api = api
        game.dll_override = dll
        game.install_path = exe.parent
        game.selected_exe = exe

        console.print(f"\n[green]Detected: {api.upper()}, {arch}-bit -> {dll}.dll[/]")
        console.print(f"[dim]Install path: {game.install_path}[/]")

    return game


def configure_dll_override(game: GameInfo) -> GameInfo:
    """Let user confirm or change the DLL override."""
    choices = []

    for dll_name, description in DLL_OPTIONS:
        title = f"{dll_name}.dll ({description})"
        if dll_name == game.dll_override:
            title += " [detected]"
            choices.insert(0, questionary.Choice(title, value=dll_name))
        else:
            choices.append(questionary.Choice(title, value=dll_name))

    result = ask_select("Select DLL override:", choices)
    if result:
        game.dll_override = result

    return game


def select_shader_repos() -> list[tuple]:
    """Let user select which shader repositories to install."""
    choices = [
        questionary.Choice(title=name, value=(url, name, branch), checked=True)
        for url, name, branch in SHADER_REPOS
    ]

    result = questionary.checkbox(
        "Select shader repositories to install:",
        choices=choices,
        style=QUESTIONARY_STYLE,
    ).ask()

    return result or []


def main_menu(installer: ReShadeInstaller) -> Optional[str]:
    """Display main menu and get user choice."""
    saved_games = installer.games_config.list_all()

    choices = [
        questionary.Choice("Install ReShade to a game", value="install"),
        questionary.Choice("Uninstall ReShade from a game", value="uninstall"),
        questionary.Choice("Update shaders", value="update_shaders"),
        questionary.Choice("Update ReShade", value="update_reshade"),
    ]

    if saved_games:
        choices.append(questionary.Choice(
            f"Reinstall to saved game ({len(saved_games)} saved)",
            value="reinstall",
        ))

    choices.extend([
        questionary.Choice("Settings", value="settings"),
        questionary.Choice("Exit", value="exit"),
    ])

    return ask_select("What would you like to do?", choices)


def run_install_flow(installer: ReShadeInstaller) -> None:
    """Run the installation flow."""
    console.print("\n[bold cyan]Scanning for Steam games...[/]")
    games = installer.steam_scanner.scan_for_games()
    console.print(f"[green]Found {len(games)} games[/]\n")

    selection = select_game(games)

    if selection is None:
        return
    elif selection == "manual":
        game = browse_for_game()
        if not game:
            return
    else:
        game = selection

    # Analyze executable
    game = select_exe_for_analysis(game, installer)

    # Confirm/change DLL override
    if not ask_confirm(f"Use {game.dll_override}.dll as override?", default=True):
        game = configure_dll_override(game)

    # Install
    console.print(f"\n[bold cyan]Installing ReShade to {game.name}...[/]\n")

    try:
        dll_used = installer.install_to_game(game)

        console.print(Panel(
            f"""[bold green]Installation complete![/]

[cyan]Game:[/] {game.name}
[cyan]Install path:[/] {game.install_path}
[cyan]API:[/] {game.detected_api.upper()} ({game.architecture}-bit)
[cyan]DLL:[/] {dll_used}.dll

[yellow]Steam Launch Options:[/]
[bold]WINEDLLOVERRIDES="d3dcompiler_47=n;{dll_used}=n,b" %command%[/]

[dim]Copy this to Steam -> Right-click game -> Properties -> Launch Options[/]""",
            title="Success",
            box=box.ROUNDED,
        ))

    except Exception as e:
        console.print(f"[bold red]Installation failed: {e}[/]")


def run_reinstall_flow(installer: ReShadeInstaller) -> None:
    """Reinstall to a previously configured game."""
    saved_games = installer.games_config.list_all()

    if not saved_games:
        console.print("[yellow]No saved games found.[/]")
        return

    choices = [
        questionary.Choice(
            title=f"{g.name} ({g.detected_api.upper()}, {g.architecture}-bit)",
            value=g,
        )
        for g in saved_games
    ]
    choices.append(questionary.Choice(title="[Cancel]", value=None))

    game = ask_select("Select a saved game to reinstall:", choices)

    if not game:
        return

    console.print(f"\n[bold cyan]Reinstalling ReShade to {game.name}...[/]\n")

    try:
        dll_used = installer.install_to_game(game)
        console.print(f"[bold green]Reinstalled successfully! DLL: {dll_used}.dll[/]")
    except Exception as e:
        console.print(f"[bold red]Reinstallation failed: {e}[/]")


def run_uninstall_flow(installer: ReShadeInstaller) -> None:
    """Run the uninstallation flow."""
    console.print("\n[bold cyan]Scanning for games...[/]")
    games = installer.steam_scanner.scan_for_games()

    selection = select_game(games)

    if selection is None:
        return
    elif selection == "manual":
        game = browse_for_game()
        if not game:
            return
    else:
        game = selection

    game = select_exe_for_analysis(game, installer)

    if ask_confirm(f"Uninstall ReShade from {game.install_path}?"):
        removed = installer.uninstall_from_game(game.install_path)
        if removed:
            console.print(f"[green]Removed: {', '.join(removed)}[/]")
            installer.games_config.remove(game.path)
        else:
            console.print("[yellow]No ReShade files found to remove[/]")

        console.print("\n[yellow]Remember to remove the WINEDLLOVERRIDES from Steam launch options![/]")


def run_settings_menu(installer: ReShadeInstaller) -> None:
    """Settings configuration menu."""
    while True:
        console.print(f"""
[bold cyan]Current Settings:[/]
  Main path: {installer.config.main_path}
  ReShade version: {installer.config.reshade_version}
  Addon support: {installer.config.addon_support}
  Merge shaders: {installer.config.merge_shaders}
  Saved games: {len(installer.games_config.list_all())}
""")

        choices = [
            questionary.Choice("Toggle addon support", value="addon"),
            questionary.Choice("Toggle shader merging", value="merge"),
            questionary.Choice("Clear saved games", value="clear_games"),
            questionary.Choice("Back to main menu", value="back"),
        ]

        choice = ask_select("Configure:", choices)

        if choice == "addon":
            installer.config.addon_support = not installer.config.addon_support
            console.print(f"[green]Addon support: {installer.config.addon_support}[/]")
        elif choice == "merge":
            installer.config.merge_shaders = not installer.config.merge_shaders
            console.print(f"[green]Merge shaders: {installer.config.merge_shaders}[/]")
        elif choice == "clear_games":
            if ask_confirm("Clear all saved game configurations?", default=False):
                installer.config.games_config_path.unlink(missing_ok=True)
                installer.games_config = GamesConfigManager(installer.config.games_config_path)
                console.print("[green]Saved games cleared.[/]")
        elif choice == "back" or choice is None:
            break


def initial_setup(installer: ReShadeInstaller) -> bool:
    """Run initial setup if needed. Returns False if setup fails."""
    reshade_dll = installer.config.reshade_path / "latest" / "ReShade64.dll"

    if not reshade_dll.exists():
        console.print("\n[cyan]First run detected. Setting up ReShade...[/]\n")

        try:
            version, url = installer.get_latest_reshade_version()
            console.print(f"[green]Latest ReShade version: {version}[/]")
            installer.download_reshade(version, url)
        except Exception as e:
            console.print(f"[red]Failed to download ReShade: {e}[/]")
            return False

    # Check for shaders
    shader_count = len(list(installer.config.merged_path.glob("Shaders/*.fx")))
    if shader_count == 0:
        if ask_confirm("No shaders installed. Download shader repositories now?", default=True):
            repos = select_shader_repos()
            if repos:
                installer.download_all_shaders(repos)

        installer.create_reshade_ini()

    return True


def main() -> None:
    """Main entry point."""
    display_banner()

    installer = ReShadeInstaller()
    installer.setup_directories()

    if not initial_setup(installer):
        sys.exit(1)

    while True:
        console.print()
        action = main_menu(installer)

        if action == "install":
            run_install_flow(installer)
        elif action == "uninstall":
            run_uninstall_flow(installer)
        elif action == "reinstall":
            run_reinstall_flow(installer)
        elif action == "update_shaders":
            repos = select_shader_repos()
            if repos:
                installer.download_all_shaders(repos)
        elif action == "update_reshade":
            try:
                version, url = installer.get_latest_reshade_version()
                console.print(f"[cyan]Downloading ReShade {version}...[/]")
                installer.download_reshade(version, url)
                console.print(f"[green]ReShade updated to {version}[/]")
            except Exception as e:
                console.print(f"[red]Update failed: {e}[/]")
        elif action == "settings":
            run_settings_menu(installer)
        elif action == "exit" or action is None:
            console.print("[cyan]Goodbye![/]")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(0)
