#!/usr/bin/env python3
"""Select a transferred study-data folder and start the local annotation tool."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, help='Folder containing transferred study sessions')
    ap.add_argument('--processing', type=Path, help='Optional separately processed aligned sessions')
    ap.add_argument('--out', type=Path, help='Annotation folder; defaults to ROOT/annotations')
    ap.add_argument('--suggestions', type=Path, help='Optional candidate-hold JSON folder')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args()
    if args.root is None:
        try:
            import tkinter as tk
            from tkinter.filedialog import askdirectory
            window = tk.Tk()
            window.withdraw()
            folder = askdirectory(title='Select the shared hand-study data folder')
            window.destroy()
            if not folder:
                return
            args.root = Path(folder)
        except ImportError:
            ap.error('Provide --root /path/to/shared-study-data (folder picker is unavailable).')
    import study_annotation_server
    found = study_annotation_server.discover(args.root, args.processing)
    if not found:
        ap.error('No usable sessions found. Check the data-folder layout in README.md.')
    # Each launcher owns its browser-open check; never open an unrelated existing app.
    url = f'http://127.0.0.1:{args.port}'
    try:
        urllib.request.urlopen(url+'/sessions', timeout=1)
    except Exception:
        pass
    else:
        ap.error('That port is already serving a tool. Close it or choose --port 8766.')
    command = [sys.executable, '-B', str(HERE/'study_annotation_server.py'),
               '--root', str(args.root.resolve()), '--port', str(args.port)]
    for flag in ['processing', 'out', 'suggestions']:
        value = getattr(args, flag)
        if value:
            command += ['--'+flag, str(value.resolve())]
    process = subprocess.Popen(command)
    def open_when_ready():
        for _ in range(120):
            if process.poll() is not None:
                return
            try:
                with urllib.request.urlopen(url+'/sessions', timeout=1) as response:
                    payload = json.load(response)
                    if 'sessions' in payload:
                        webbrowser.open(url)
                        return
            except Exception:
                time.sleep(.25)
    threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        raise SystemExit(process.wait())
    except KeyboardInterrupt:
        process.terminate()
        process.wait()


if __name__ == '__main__':
    main()
