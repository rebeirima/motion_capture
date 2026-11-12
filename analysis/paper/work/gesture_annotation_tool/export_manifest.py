#!/usr/bin/env python3
"""Write portable frame-count metadata for separately transferred study videos.

This copies no videos or annotations. It never uploads anything.
"""
import argparse
import json
from pathlib import Path
from study_annotation_server import discover


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--processing', type=Path)
    ap.add_argument('--output', type=Path, required=True,
                    help='Save as annotation_sessions.json beside the transferred data')
    args = ap.parse_args()
    sessions = discover(args.root, args.processing)
    if not sessions:
        ap.error('No usable sessions found; no manifest was written.')
    payload = {'format_version': 2, 'sessions': [
        dict({k: s[k] for k in ('session_id', 'participant_id', 'hand', 'frame_count', 'fps')},
             **({'display_to_recorded': [v['recorded_camera'] for v in s['camera_views']]} if s['camera_mapping_verified'] else {}))
        for s in sessions.values()]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(payload, f, indent=2)
    print(f'Wrote {len(sessions)} sessions to {args.output}. Transfer this file privately with the videos.')


if __name__ == '__main__':
    main()
