#!/data/data/com.termux/files/usr/bin/sh
set -eu
cd "$(dirname "$0")"
exec python -m android_agent --open-browser
