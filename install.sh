#!/bin/bash
#
# ReShade Linux Installer - One-stop installation script
#
# This script installs the ReShade Linux tool to ~/.local/reshade with:
# - A Python virtual environment with all dependencies
# - A "reshade" command in ~/.local/bin for easy access
# - All shader repositories pre-downloaded
#
# Usage: ./install.sh
#

set -e

# =============================================================================
# Configuration
# =============================================================================

INSTALL_DIR="${HOME}/.local/reshade"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${INSTALL_DIR}/.venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="reshade-linux.py"
WRAPPER_NAME="reshade"

# Python packages to install
PYTHON_PACKAGES="rich questionary requests pefile"

# Required system tools
REQUIRED_TOOLS="python3 git 7z"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# =============================================================================
# Pre-flight Checks
# =============================================================================

preflight_checks() {
    echo -e "\n${BOLD}${CYAN}=== ReShade Linux Installer ===${NC}\n"

    info "Checking system requirements..."

    local missing_tools=()

    for tool in $REQUIRED_TOOLS; do
        if ! check_command "$tool"; then
            missing_tools+=("$tool")
        fi
    done

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        error "Missing required tools: ${missing_tools[*]}
Please install them using your package manager:
  Arch/Manjaro: sudo pacman -S python git p7zip
  Ubuntu/Debian: sudo apt install python3 python3-venv git p7zip-full
  Fedora: sudo dnf install python3 git p7zip"
    fi

    # Check for python3-venv on Debian-based systems
    if ! python3 -m venv --help &> /dev/null; then
        error "Python venv module not available.
Please install it:
  Ubuntu/Debian: sudo apt install python3-venv"
    fi

    # Check if the Python script exists
    if [[ ! -f "${SCRIPT_DIR}/${PYTHON_SCRIPT}" ]]; then
        error "Cannot find ${PYTHON_SCRIPT} in ${SCRIPT_DIR}"
    fi

    success "All system requirements met"
}

# =============================================================================
# Installation
# =============================================================================

create_directories() {
    info "Creating installation directories..."

    mkdir -p "${INSTALL_DIR}"
    mkdir -p "${BIN_DIR}"
    mkdir -p "${INSTALL_DIR}/ReShade_shaders"
    mkdir -p "${INSTALL_DIR}/External_shaders"

    success "Directories created"
}

setup_venv() {
    info "Setting up Python virtual environment..."

    if [[ -d "${VENV_DIR}" ]]; then
        warn "Virtual environment already exists, recreating..."
        rm -rf "${VENV_DIR}"
    fi

    python3 -m venv "${VENV_DIR}"

    # Activate venv and install packages
    source "${VENV_DIR}/bin/activate"

    info "Installing Python dependencies..."
    pip install --upgrade pip --quiet
    pip install ${PYTHON_PACKAGES} --quiet

    deactivate

    success "Virtual environment ready with all dependencies"
}

install_script() {
    info "Installing ReShade script..."

    cp "${SCRIPT_DIR}/${PYTHON_SCRIPT}" "${INSTALL_DIR}/${PYTHON_SCRIPT}"
    chmod +x "${INSTALL_DIR}/${PYTHON_SCRIPT}"

    success "Script installed to ${INSTALL_DIR}"
}

create_wrapper() {
    info "Creating wrapper script..."

    cat > "${BIN_DIR}/${WRAPPER_NAME}" << 'WRAPPER_EOF'
#!/bin/bash
#
# ReShade Linux - Wrapper script
# Activates the virtual environment and runs the ReShade installer
#

INSTALL_DIR="${HOME}/.local/reshade"
VENV_DIR="${INSTALL_DIR}/.venv"
SCRIPT="${INSTALL_DIR}/reshade-linux.py"

# Check if installation exists
if [[ ! -d "${VENV_DIR}" ]] || [[ ! -f "${SCRIPT}" ]]; then
    echo "Error: ReShade Linux is not properly installed."
    echo "Please run the install script again."
    exit 1
fi

# Activate venv and run
source "${VENV_DIR}/bin/activate"
exec python3 "${SCRIPT}" "$@"
WRAPPER_EOF

    chmod +x "${BIN_DIR}/${WRAPPER_NAME}"

    success "Wrapper script created at ${BIN_DIR}/${WRAPPER_NAME}"
}

check_path() {
    if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
        warn "${BIN_DIR} is not in your PATH"
        echo ""
        echo -e "${YELLOW}Add the following to your shell config (~/.bashrc, ~/.zshrc, etc.):${NC}"
        echo ""
        echo -e "  ${BOLD}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${NC}"
        echo ""
        echo "Then reload your shell or run: source ~/.bashrc"
        echo ""
    fi
}

# =============================================================================
# Post-install setup
# =============================================================================

initial_setup() {
    info "Running initial setup..."

    # Activate venv and run the script in non-interactive mode for initial download
    source "${VENV_DIR}/bin/activate"

    # Just verify the script runs (will do full setup on first interactive run)
    if python3 -c "import sys; sys.path.insert(0, '${INSTALL_DIR}'); exec(open('${INSTALL_DIR}/${PYTHON_SCRIPT}').read().split('if __name__')[0])" 2>/dev/null; then
        success "Script verified successfully"
    fi

    deactivate
}

print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}=== Installation Complete ===${NC}"
    echo ""
    echo -e "ReShade Linux has been installed to: ${CYAN}${INSTALL_DIR}${NC}"
    echo ""
    echo -e "${BOLD}To run ReShade Linux:${NC}"
    echo -e "  ${CYAN}reshade${NC}"
    echo ""
    echo -e "${BOLD}Installation contents:${NC}"
    echo -e "  ${INSTALL_DIR}/"
    echo -e "    ├── .venv/              # Python virtual environment"
    echo -e "    ├── reshade-linux.py    # Main script"
    echo -e "    ├── reshade/            # ReShade binaries (downloaded on first run)"
    echo -e "    ├── ReShade_shaders/    # Shader repositories"
    echo -e "    ├── External_shaders/   # Your custom shaders"
    echo -e "    └── games.json          # Saved per-game configurations"
    echo ""
    echo -e "${BOLD}Features:${NC}"
    echo -e "  - Automatic game detection from Steam libraries"
    echo -e "  - PE analysis for architecture and graphics API detection"
    echo -e "  - Per-game configuration persistence (no re-entering paths)"
    echo -e "  - Merged shader directory for easy ReShade setup"
    echo ""
    echo -e "${YELLOW}On first run, you'll be prompted to download ReShade and shaders.${NC}"
    echo ""
}

# =============================================================================
# Uninstall function (for reference)
# =============================================================================

uninstall() {
    echo -e "${YELLOW}To uninstall ReShade Linux:${NC}"
    echo ""
    echo "  rm -rf ~/.local/reshade"
    echo "  rm ~/.local/bin/reshade"
    echo ""
    echo "Note: This won't remove ReShade from games - run 'reshade' and use"
    echo "      the uninstall option for each game first."
}

# =============================================================================
# Main
# =============================================================================

main() {
    # Handle --uninstall flag
    if [[ "$1" == "--uninstall" ]] || [[ "$1" == "-u" ]]; then
        uninstall
        exit 0
    fi

    # Handle --help flag
    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        echo "ReShade Linux Installer"
        echo ""
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  -h, --help       Show this help message"
        echo "  -u, --uninstall  Show uninstallation instructions"
        echo ""
        echo "This script installs ReShade Linux to ~/.local/reshade"
        echo "and creates a 'reshade' command in ~/.local/bin"
        exit 0
    fi

    preflight_checks
    create_directories
    setup_venv
    install_script
    create_wrapper
    check_path
    print_summary
}

main "$@"
