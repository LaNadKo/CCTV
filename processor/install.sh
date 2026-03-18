#!/usr/bin/env bash
# ============================================================
#  CCTV Processor — Install script (Linux / macOS)
#  Creates Python venv, installs dependencies (with GPU if available),
#  and optionally creates a systemd service for auto-start.
#
#  Usage: chmod +x install.sh && ./install.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON="${PYTHON:-python3}"

echo "=== CCTV Processor — Installer ==="
echo ""

# ── Check Python ──────────────────────────────────────────
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: $PYTHON not found. Install Python 3.10+ first."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora:        sudo dnf install python3"
    echo "  macOS:         brew install python3"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PYTHON ($PY_VERSION)"

# ── Check GPU ─────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    echo "GPU:    $GPU"
    TORCH_INDEX="https://download.pytorch.org/whl/cu124"
    echo "        → Installing CUDA-enabled PyTorch"
else
    echo "GPU:    not detected (CPU mode)"
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
fi
echo ""

# ── Create virtual environment ────────────────────────────
echo "[1/3] Creating virtual environment..."
"$PYTHON" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# ── Install PyTorch ───────────────────────────────────────
echo "[2/3] Installing PyTorch (this may take a few minutes)..."
pip install torch torchvision --index-url "$TORCH_INDEX" -q

# ── Install remaining dependencies ────────────────────────
echo "[3/3] Installing dependencies..."
pip install -r "$SCRIPT_DIR/requirements.txt" -q

echo ""
echo "=== Installation complete ==="
echo ""

# ── Create .env if not exists ─────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "Created .env from template."
    echo ""

    # Interactive setup
    read -p "Server URL (e.g. https://cctv.example.com): " BACKEND_URL
    if [ -n "$BACKEND_URL" ]; then
        sed -i "s|BACKEND_URL=.*|BACKEND_URL=$BACKEND_URL|" "$SCRIPT_DIR/.env"
    fi

    read -p "API key: " API_KEY_VAL
    if [ -n "$API_KEY_VAL" ]; then
        sed -i "s|API_KEY=.*|API_KEY=$API_KEY_VAL|" "$SCRIPT_DIR/.env"
    fi

    HOSTNAME_DEFAULT=$(hostname)
    read -p "Processor name [$HOSTNAME_DEFAULT]: " PROC_NAME
    PROC_NAME=${PROC_NAME:-$HOSTNAME_DEFAULT}
    sed -i "s|PROCESSOR_NAME=.*|PROCESSOR_NAME=$PROC_NAME|" "$SCRIPT_DIR/.env"

    echo ""
fi

# ── Create run.sh ─────────────────────────────────────────
cat > "$SCRIPT_DIR/run.sh" << 'RUNEOF'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
set -a; source "$SCRIPT_DIR/.env" 2>/dev/null; set +a
cd "$(dirname "$SCRIPT_DIR")"
exec python -m processor.main
RUNEOF
chmod +x "$SCRIPT_DIR/run.sh"

# ── Create systemd service (Linux only) ──────────────────
if [ "$(uname)" = "Linux" ] && command -v systemctl &>/dev/null; then
    SERVICE_FILE="$SCRIPT_DIR/cctv-processor.service"
    cat > "$SERVICE_FILE" << SVCEOF
[Unit]
Description=CCTV Processor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python -m processor.main
EnvironmentFile=$SCRIPT_DIR/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

    echo "── Auto-start setup (systemd) ──"
    echo ""
    echo "To install as system service (auto-starts on boot):"
    echo "  sudo cp $SERVICE_FILE /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now cctv-processor"
    echo ""
    echo "Service commands:"
    echo "  sudo systemctl status cctv-processor   — status"
    echo "  sudo systemctl restart cctv-processor   — restart"
    echo "  journalctl -u cctv-processor -f         — logs"
    echo ""
fi

echo "── Run manually ──"
echo "  $SCRIPT_DIR/run.sh"
echo ""
echo "── Run with GUI ──"
echo "  source $VENV_DIR/bin/activate && python $SCRIPT_DIR/launcher.py"
echo ""
