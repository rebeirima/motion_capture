# Annotate the remaining hand recordings

This tool opens **physical C2 (center-camera) videos for hands that still need annotation**. Completed hands are excluded from the supplied queue. Camera identity is resolved separately for each recording; recorded `cam2` is not assumed to be physical C2.

## Quick start

1. Download [Annotation_tool.zip](https://github.com/rebeirima/motion_capture/raw/refs/heads/main/analysis/paper/work/gesture_annotation_tool/Annotation_tool.zip) and unzip it.
2. Install Python 3.10 or newer if needed. No other Python packages, FFmpeg, or hosting account are needed for the supplied videos.
3. Open a terminal in the unzipped folder and run:

   ```sh
   python3 launch.py
   ```

   On Windows use `py -3 launch.py`. The launcher downloads any missing supplied videos from this repository, verifies their checksums, and opens the tool in your browser at `http://127.0.0.1:8765`. Keep the terminal open while working. Stop with Ctrl+C.

## Annotate

- Choose a hand. Mark only the stable part of each hold, excluding movement transitions.
- Each hand requires **29 windows: neutral/baseline once and 14 gestures twice**. Leave the four optional wrist windows blank.
- **S** marks the start, **E** the end, **N** selects the next row, Space plays/pauses, and arrow keys step through frames. Start and end frame numbers are inclusive.
- Leave uncertain or missing holds blank. Do not assign gestures from recording order alone.
- Click **Save versioned CSV** regularly. Browser drafts are not saved annotation files.
- Only C2 is supplied, so the other-camera button is disabled.

## Return the work

Send the study owner the **`annotations/` folder**, including each session’s CSV files and matching JSON files. Videos do not need to be returned. Saved annotations remain on your computer; the tool does not upload them to GitHub.

Earlier saved versions remain intact, and identical resaves create no duplicate. The app rejects overlaps, invalid frame boundaries, unreviewed candidate holds, and saves that conflict with a newer version from another browser.

## Files

- `included_videos.json`: supplied queue, physical-to-recorded camera mapping, frame counts, download URLs, and checksums.
- `annotation_videos/`: the actual low-resolution C2 videos on GitHub; the launcher downloads missing files automatically.
- `examples/`: the earlier separately approved S017 C2 demonstration. It is **not** part of the remaining-hands queue.
- `test_annotation_tool.py`: isolated tests using synthetic data, run with `python3 -B test_annotation_tool.py`.

For a separately prepared multiview study folder, run `python3 launch.py --root "/path/to/shared-study-data"`. That folder needs synchronized aligned `S.../aligned/cam0.mkv` through `cam4.mkv`, or a portable `annotation_sessions.json` and all five `video_proxies/S.../camN_480p_v2.mp4` files. MKV inputs require FFmpeg/ffprobe. Add `--processing "/path/to/processed-sessions"` if aligned files are stored separately. Source camera mappings are read from `metadata/camera_mapping.txt`, or `display_to_recorded` in the transfer manifest; unverified camera positions are explicitly labeled.

The server listens only on the local computer. It has no remote authentication and should not be exposed to the internet. Original study recordings are never modified.
