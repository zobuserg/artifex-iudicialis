#!/usr/bin/env bash
# WikiJuez — setup completo en macOS
# Instala Homebrew → Python 3 → venv → dependencias → lanza la app
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓ $1${NC}"; }
info() { echo -e "${CYAN}▸ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  WikiJuez — instalación automática macOS     ${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""

# ── 1. Homebrew ─────────────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
    ok "Homebrew ya está instalado ($(brew --version | head -1))"
else
    info "Instalando Homebrew (también instala Xcode CLT)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Añadir al PATH para esta sesión (Apple Silicon)
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
    ok "Homebrew instalado"
fi

# ── 2. Python 3 ──────────────────────────────────────────────────────────────
if command -v python3 &>/dev/null && python3 --version &>/dev/null 2>&1; then
    PYVER=$(python3 --version)
    ok "Python ya disponible: $PYVER"
else
    info "Instalando Python 3 via Homebrew..."
    brew install python3
    ok "Python 3 instalado"
fi

PYTHON=$(command -v python3)
info "Usando: $PYTHON  ($($PYTHON --version))"

# ── 3. Entorno virtual ───────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/.venv"
if [[ -d "$VENV" ]]; then
    ok "Entorno virtual ya existe (.venv/)"
else
    info "Creando entorno virtual en .venv/ ..."
    "$PYTHON" -m venv "$VENV"
    ok "Entorno virtual creado"
fi

source "$VENV/bin/activate"
ok "Entorno virtual activado"

# ── 4. Dependencias ──────────────────────────────────────────────────────────
info "Instalando dependencias (PyQt6, ollama, pdfplumber)..."
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/app/requirements.txt"
ok "Dependencias instaladas"

# ── 5. Verificar Ollama ──────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    ok "Ollama disponible ($(ollama --version 2>/dev/null || echo 'instalado'))"
else
    warn "Ollama no encontrado en PATH — asegúrate de haberlo instalado"
    warn "  curl -fsSL https://ollama.com/install.sh | sh"
fi

# ── 6. Lanzar la app ─────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Instalación completa — iniciando WikiJuez${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "Para relanzar la app manualmente:"
echo -e "  ${CYAN}source .venv/bin/activate && python app/main.py${NC}"
echo ""

python "$SCRIPT_DIR/app/main.py"
