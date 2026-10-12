#!/usr/bin/env bash
# Abre a Ferramenta de Gestão Industrial no navegador (http://localhost:8501).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    echo "A ferramenta ainda não foi instalada. Rode: bash instalador/instalar_mac_linux.sh"
    exit 1
fi
echo "Abrindo a ferramenta no navegador. Para encerrar, aperte Ctrl+C neste Terminal."
exec .venv/bin/python -m streamlit run streamlit_app.py --server.headless false
