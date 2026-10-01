#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$project_dir/scripts/build.py"
gnome-extensions install --force "$project_dir/dist/quota-panel@extensions.local.shell-extension.zip"
if gnome-extensions enable quota-panel@extensions.local; then
    printf '%s\n' 'Quota Panel activada. Preferencias: gnome-extensions prefs quota-panel@extensions.local'
else
    printf '%s\n' 'Instalada. Cierra y abre tu sesión de GNOME y actívala desde Extensiones.'
fi
