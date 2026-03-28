# ReShade Linux

A CLI tool for installing [ReShade](https://reshade.me) on Linux for Steam games running via Wine/Proton.

![screenshot](screenshot.png)

## Features

- Automatic Steam library scanning and game detection
- PE analysis for architecture (32/64-bit) and graphics API (DX8/9/10/11/12, OpenGL)
- Per-game configuration persistence
- Shader repository management with automatic merging
- Addon support enabled by default

## Requirements

- Python 3.10+
- `git`
- `7z` (p7zip)

### Install dependencies

```bash
# Arch/Manjaro
sudo pacman -S python git p7zip

# Ubuntu/Debian
sudo apt install python3 python3-venv git p7zip-full

# Fedora
sudo dnf install python3 git p7zip
```

## Install

```bash
git clone https://github.com/nesdeq/reshade.git
cd reshade
./install.sh
```

Installs to `~/.local/reshade` and creates the `reshade` command in `~/.local/bin`.

## Usage

```bash
reshade
```

After installing ReShade to a game, set Steam launch options (right-click game > Properties > Launch Options):

```
WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b" %command%
```

Replace `dxgi` with the DLL shown after installation (e.g. `d3d9` for DX9 games).

## Custom shaders

Drop `.fx` files into `~/.local/reshade/External_shaders/` and run "Update shaders" from the menu.

## Shader repositories

- [reshade-shaders](https://github.com/crosire/reshade-shaders) (slim)
- [SweetFX](https://github.com/CeeJayDK/SweetFX)
- [qUINT](https://github.com/martymcmodding/qUINT)
- [AstrayFX](https://github.com/BlueSkyDefender/AstrayFX)
- [prod80](https://github.com/prod80/prod80-ReShade-Repository)

## Uninstall

Remove ReShade from games via the tool first, then:

```bash
rm -rf ~/.local/reshade ~/.local/bin/reshade
```

## License

GPL-2.0 — Based on [reshade-steam-proton](https://github.com/kevinlekiller/reshade-steam-proton) by kevinlekiller.
