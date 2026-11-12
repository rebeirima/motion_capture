# Local hand-gesture annotation tool

Review synchronized camera recordings and mark stable gesture holds in a browser on your own computer. The server runs only at `127.0.0.1`; it requires no hosting account, cloud service, sign-in, or Python packages.

This folder contains the tool, **not the full study videos or participant annotations**. The `examples/` folder includes one explicitly approved, low-resolution C2 demonstration recording. Get those separately from the study owner using the agreed private transfer method.

## Start

1. Install **Python 3.10 or newer**. If you received aligned `.mkv` files rather than precomputed previews, also install [FFmpeg](https://ffmpeg.org/download.html), including `ffprobe`, and make both commands available on your PATH. On macOS with Homebrew: `brew install ffmpeg`.
2. Download this tool folder and keep its files together.
3. Open a terminal in this folder and run:

   ```sh
   python3 launch.py --root "/path/to/shared-study-data"
   ```

   On Windows, use `py -3 launch.py --root "C:\path\to\shared-study-data"`.

   You can instead run `python3 launch.py` and select the data folder in the folder picker. The included Mac `.command` and Windows `.bat` files do the same thing.
4. Your browser opens at **http://127.0.0.1:8765**. Keep the terminal open while annotating. Stop with Ctrl+C.

If that port is occupied, add `--port 8766`. If a separately processed folder supplies the aligned videos, add `--processing "/path/to/processed-sessions"`. You can choose another saved-annotation destination with `--out "/path/to/annotations"`.

## Data-folder layout

Use either aligned recordings or the existing frame-preserving previews. Session names must keep the original `S..._L/R_hand_gestures_...` identifiers.

### Option A: aligned recordings

```text
shared-study-data/
  annotation_sessions.json                 # strongly recommended; shared frame counts
  S001_L_hand_gestures_YYYYMMDD_HHMMSS/
    aligned/
      cam0.mkv
      cam1.mkv
      cam2.mkv
      cam3.mkv
      cam4.mkv
  annotations/                             # existing CSV + matching JSON versions, if supplied
    S001_L_hand_gestures_YYYYMMDD_HHMMSS/
      gesture_windows_TIMESTAMP_ID.csv
      gesture_windows_TIMESTAMP_ID.json
  suggestions/                             # optional candidate-hold JSONs
```

The tool reads shared frame counts from `annotation_sessions.json`, a processing-state file, or the existing landmark NPZ. If none is available, it counts the actual aligned 30-fps video frames and uses their common range. That first scan can take time. It creates small H.264 previews on demand under the annotation destination's `video_proxies/`, without resampling the frames or editing the source videos.

### Option B: precomputed previews only

```text
shared-study-data/
  annotation_sessions.json                 # required with previews-only transfer
  video_proxies/
    S001_L_hand_gestures_YYYYMMDD_HHMMSS/
      cam0_480p_v2.mp4
      cam1_480p_v2.mp4
      cam2_480p_v2.mp4
      cam3_480p_v2.mp4
      cam4_480p_v2.mp4
  annotations/                             # optional prior CSV + JSON versions
  suggestions/                             # optional candidate-hold JSONs
```

All five matching camera previews are required for a previews-only session. Use the frame-preserving previews produced by this tool; do not trim, change frame rate, reorder, or independently realign them. The manifest must describe the exact shared timeline being annotated. Do not use raw unsynchronized recordings as aligned input.

The owner can export the manifest from the current study files:

```sh
python3 export_manifest.py --root "/path/to/motion_capture" \
  --processing "/path/to/processed-sessions" \
  --output "/path/to/private-transfer/annotation_sessions.json"
```

This command writes metadata only; it copies no videos and uploads nothing. It refuses to overwrite an existing manifest.

## Annotating

- Select a hand; the dropdown shows saved progress. **Next unfinished hand** skips hands with all 29 required windows saved.
- Mark the stable portion of each hold, excluding movement transitions. There are **29 required hand windows**: neutral/baseline once and 14 gestures twice. Four wrist windows remain optional.
- Use **S** for start, **E** for end, **N** for the next row, Space for playback, and arrow keys for frame stepping. Start/end frame numbers are inclusive.
- Check uncertain holds in the other recorded camera views. C0–C4 match the paper’s physical camera positions, with C2 at the center. The tool maps them to each session’s recorded files; recording filenames alone do not establish physical camera position.
- Candidate holds are optional drafts, not verified labels. Review any accepted candidate and tick its Reviewed box before saving. Do not infer gesture labels from recording order alone.
- Click **Save versioned CSV** regularly. Browser drafts are local to that browser; a draft is not a saved annotation file.

## Saved files and returning the work

Annotations save to `shared-study-data/annotations/SESSION_ID/` unless `--out` selects another destination. Each changed save creates a new CSV and matching checksum metadata JSON. Earlier versions remain intact; resaving identical annotations creates no duplicate. Existing versions reload automatically, and the UI can restore older versions.

Return the **session folders containing CSV + JSON files** to the study owner. Preserve the full filenames and matching JSONs. The owner should merge version files without replacing different files of the same name. Videos and regenerated previews do not need to be returned.

The app rejects overlaps, out-of-range boundaries, duplicate slots, and unreviewed suggested holds. If another browser saved since your loaded version, it asks you to load the latest version and reconcile edits; your browser draft is retained. Run only one server process for a given annotation destination.

## Troubleshooting

- **No sessions found:** select the parent data folder, not an individual `aligned/` folder. Check all five camera filenames and supply the manifest for previews-only data.
- **Missing FFmpeg:** install FFmpeg/ffprobe or request the completed precomputed previews and manifest.
- **Video preparing:** first opening an MKV can take time to create the preview. Later visits reuse it.
- **Saved hand looks unfinished:** check whether the latest version is partial; an older complete version remains available in the version selector.
- **Do not publish this local server:** it has no remote authentication and intentionally listens only on the computer's loopback address. Use the local browser URL above.

Run the isolated checks with `python3 -B test_annotation_tool.py`. They use synthetic session data and do not access study recordings.

## Camera identity and newly added recordings

The physical arc order C0..C4 corresponds to calibration indices `[4, 1, 3, 2, 0]`, as in the paper-analysis code. Each session’s `metadata/camera_mapping.txt` states `calibration k <- recorded mapping[k]`. The tool composes these two mappings rather than assuming recorded `cam2` is the center. A transferred manifest can instead provide `display_to_recorded` (five recorded indices in physical C0..C4 order).

Saved CSVs retain `reference_recorded_camera` in the original recorded-file convention. Existing annotations remain compatible. When mapping metadata is absent, the app labels the views **Recorded camN (position unverified)**; it does not guess the center camera. The main video is hidden and marking controls disabled until the requested view loads, preventing the dropdown from labeling an older frame as the newly selected camera.

**Refresh sessions** rescans the data folder. New raw-only folders appear in the preparation notice; they become selectable after synchronized aligned videos or frame-preserving synchronized previews and timeline metadata are supplied. Raw videos must be synchronized before cross-view annotations share a frame timeline.

## Included C2 example

`examples/C2_center_480p.mp4` is the S017 left-hand center-camera preview: 854×480 pixels, 30 fps, 4,394 frames (146.47 s), without audio. Its session mapping confirms physical C2 corresponds to recorded `cam2` for this specific session. See `examples/example_info.json` for the mapping and checksum. It is a playback demonstration; the complete five-view study data is transferred separately for annotation.
