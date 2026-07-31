#!/opt/anaconda3/bin/python

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from aniposelib.boards import CharucoBoard, extract_points, merge_rows
from aniposelib.cameras import CameraGroup


N_CAMERAS = 5
FPS = 30
WIDTH = 1920
HEIGHT = 1080

SQUARE_LENGTH = 0.024
MARKER_LENGTH = 0.018

BOARD = CharucoBoard(
    squaresX=7,
    squaresY=10,
    square_length=SQUARE_LENGTH,
    marker_length=MARKER_LENGTH,
    marker_bits=4,
    dict_size=50,
)


def run_command(command: list[str]) -> None:
    print("\n$", " ".join(command), flush=True)

    result = subprocess.run(
        command,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: "
            + " ".join(command)
        )


def capture_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\n{' '.join(command)}\n\n"
            f"stderr:\n{result.stderr}"
        )

    return result.stdout.strip()


def read_avfoundation_start(log_path: Path) -> float:
    text = log_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    match = re.search(
        r"Duration:\s*N/A,\s*start:\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )

    if match is None:
        raise RuntimeError(
            f"Could not find AVFoundation start time in {log_path}"
        )

    return float(match.group(1))


def probe_video(video_path: Path) -> dict[str, Any]:
    output = capture_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video_path),
        ]
    )

    data = json.loads(output)

    if not data.get("streams"):
        raise RuntimeError(
            f"No video stream found in {video_path}"
        )

    stream = data["streams"][0]
    format_data = data.get("format", {})

    duration_value = format_data.get("duration")

    if duration_value is None:
        raise RuntimeError(
            f"No duration reported for {video_path}"
        )

    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "r_frame_rate": stream.get("r_frame_rate"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "duration": float(duration_value),
        "size": int(format_data.get("size", 0)),
    }


def count_frames(video_path: Path) -> int:
    output = capture_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )

    return int(output)


def verify_inputs(
    session_path: Path,
) -> tuple[list[Path], list[Path], list[dict[str, Any]]]:
    raw_dir = session_path / "raw"
    log_dir = session_path / "logs"

    raw_videos = [
        raw_dir / f"cam{i}.mkv"
        for i in range(N_CAMERAS)
    ]

    logs = [
        log_dir / f"cam{i}.log"
        for i in range(N_CAMERAS)
    ]

    missing = [
        path
        for path in raw_videos + logs
        if not path.exists()
    ]

    if missing:
        missing_text = "\n".join(
            str(path)
            for path in missing
        )

        raise FileNotFoundError(
            f"Missing required session files:\n{missing_text}"
        )

    metadata = []

    print("\nRaw video verification")

    for index, video_path in enumerate(raw_videos):
        info = probe_video(video_path)

        if (
            info["width"] != WIDTH
            or info["height"] != HEIGHT
        ):
            raise RuntimeError(
                f"cam{index} has resolution "
                f"{info['width']}x{info['height']}; "
                f"expected {WIDTH}x{HEIGHT}"
            )

        if info["duration"] < 10:
            raise RuntimeError(
                f"cam{index} is only "
                f"{info['duration']:.3f} seconds long"
            )

        metadata.append(info)

        print(
            f"cam{index}: "
            f"{info['duration']:.3f} s, "
            f"{info['size'] / (1024 ** 2):.1f} MiB"
        )

    return raw_videos, logs, metadata


def compute_alignment(
    logs: list[Path],
    metadata: list[dict[str, Any]],
) -> tuple[list[float], list[float], float]:
    start_times = [
        read_avfoundation_start(log)
        for log in logs
    ]

    reference_start = max(start_times)

    trims = [
        reference_start - start_time
        for start_time in start_times
    ]

    usable_durations = [
        metadata[index]["duration"] - trims[index]
        for index in range(N_CAMERAS)
    ]

    common_duration = min(usable_durations)

    # Floor to an exact 30 fps frame boundary.
    common_frames = math.floor(
        common_duration * FPS
    )

    # Remove one final frame as a guard against container rounding.
    common_frames -= 1

    if common_frames <= 0:
        raise RuntimeError(
            "Computed common aligned duration is not positive"
        )

    aligned_duration = common_frames / FPS

    print("\nAlignment parameters")
    print(f"Reference start: {reference_start:.6f}")

    for index in range(N_CAMERAS):
        print(
            f"cam{index}: "
            f"start={start_times[index]:.6f}, "
            f"front trim={trims[index]:.6f} s"
        )

    print(
        f"Common aligned duration: "
        f"{aligned_duration:.6f} s "
        f"({common_frames} frames)"
    )

    return start_times, trims, aligned_duration


def align_videos(
    session_path: Path,
    raw_videos: list[Path],
    trims: list[float],
    duration: float,
    overwrite: bool,
) -> tuple[list[Path], int]:
    aligned_dir = session_path / "aligned"
    aligned_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    aligned_videos = [
        aligned_dir / f"cam{i}.mkv"
        for i in range(N_CAMERAS)
    ]

    for index, output_path in enumerate(aligned_videos):
        if output_path.exists() and not overwrite:
            print(
                f"\nUsing existing aligned video: {output_path}"
            )
            continue

        filter_string = (
            f"trim=start={trims[index]:.6f}:"
            f"duration={duration:.6f},"
            "setpts=PTS-STARTPTS,"
            f"fps={FPS}"
        )

        run_command(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-i",
                str(raw_videos[index]),
                "-vf",
                filter_string,
                "-an",
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "8000k",
                "-pix_fmt",
                "yuv420p",
                "-fps_mode",
                "cfr",
                str(output_path),
            ]
        )

    frame_counts = [
        count_frames(video)
        for video in aligned_videos
    ]

    print("\nAligned frame counts")

    for index, frame_count in enumerate(frame_counts):
        print(f"cam{index}: {frame_count}")

    if len(set(frame_counts)) != 1:
        raise RuntimeError(
            "Aligned videos do not have identical frame counts: "
            f"{frame_counts}"
        )

    return aligned_videos, frame_counts[0]


def solve_extrinsics(
    intrinsics_path: Path,
    aligned_videos: list[Path],
    session_results_dir: Path,
) -> tuple[CameraGroup, float, Path]:
    cgroup = CameraGroup.load(
        str(intrinsics_path)
    )

    if len(cgroup.cameras) != N_CAMERAS:
        raise RuntimeError(
            f"Intrinsics contain {len(cgroup.cameras)} cameras; "
            f"expected {N_CAMERAS}"
        )

    matrices_before = [
        camera.get_camera_matrix().copy()
        for camera in cgroup.cameras
    ]

    distortions_before = [
        camera.get_distortions().copy()
        for camera in cgroup.cameras
    ]

    videos = [
        [str(video_path)]
        for video_path in aligned_videos
    ]

    print("\nStarting fixed-intrinsics extrinsic calibration")

    error, _all_rows = cgroup.calibrate_videos(
        videos,
        BOARD,
        init_intrinsics=False,
        init_extrinsics=True,
        only_extrinsics=True,
        verbose=True,
        n_iters=6,
        start_mu=15,
        end_mu=1,
        max_nfev=300,
        ftol=1e-5,
        n_samp_iter=300,
        n_samp_full=1500,
        error_threshold=0.3,
    )

    for index, camera in enumerate(cgroup.cameras):
        if not np.allclose(
            matrices_before[index],
            camera.get_camera_matrix(),
            rtol=0,
            atol=1e-12,
        ):
            raise RuntimeError(
                f"cam{index}: intrinsic matrix changed "
                "during extrinsic-only calibration"
            )

        if not np.allclose(
            distortions_before[index],
            camera.get_distortions(),
            rtol=0,
            atol=1e-12,
        ):
            raise RuntimeError(
                f"cam{index}: distortion changed "
                "during extrinsic-only calibration"
            )

    calibration_path = (
        session_results_dir / "calibration.toml"
    )

    cgroup.dump(str(calibration_path))

    print(
        f"\nExtrinsic calibration error: "
        f"{error:.4f} px"
    )
    print(
        f"Session calibration saved to: "
        f"{calibration_path}"
    )

    return cgroup, float(error), calibration_path


def validate_calibration(
    cgroup: CameraGroup,
    aligned_videos: list[Path],
    validation_stride: int,
) -> dict[str, Any]:
    videos = [
        [str(video_path)]
        for video_path in aligned_videos
    ]

    print("\nDetecting board observations for validation")

    all_rows = cgroup.get_rows_videos(
        videos,
        BOARD,
        verbose=True,
    )

    original_counts = [
        len(rows)
        for rows in all_rows
    ]

    if validation_stride > 1:
        all_rows = [
            rows[::validation_stride]
            for rows in all_rows
        ]

    selected_counts = [
        len(rows)
        for rows in all_rows
    ]

    print(
        f"Validation rows before sampling: "
        f"{original_counts}"
    )
    print(
        f"Validation rows after sampling: "
        f"{selected_counts}"
    )

    for camera_index, camera in enumerate(
        cgroup.cameras
    ):
        all_rows[camera_index] = (
            BOARD.estimate_pose_rows(
                camera,
                all_rows[camera_index],
            )
        )

    merged = merge_rows(
        all_rows,
        cam_names=cgroup.get_names(),
    )

    points_2d, extra = extract_points(
        merged,
        BOARD,
        cam_names=cgroup.get_names(),
        min_cameras=2,
        min_points=8,
        check_rtvecs=True,
    )

    if points_2d.shape[1] == 0:
        raise RuntimeError(
            "No shared board observations were found"
        )

    points_3d = cgroup.triangulate(
        points_2d
    )

    reprojection_vectors = cgroup.reprojection_error(
        points_3d,
        points_2d,
        mean=False,
    )

    reprojection_norms = np.linalg.norm(
        reprojection_vectors,
        axis=2,
    )

    valid_errors = reprojection_norms[
        np.isfinite(reprojection_norms)
    ]

    board_instance_ids = np.asarray(
        extra["ids"]
    )

    object_points = np.asarray(
        extra["objp"]
    )

    adjacent_distances: list[float] = []

    for board_instance in np.unique(
        board_instance_ids
    ):
        indices = np.where(
            board_instance_ids == board_instance
        )[0]

        finite = np.all(
            np.isfinite(points_3d[indices]),
            axis=1,
        )

        indices = indices[finite]

        if len(indices) < 2:
            continue

        obj = object_points[indices]
        tri = points_3d[indices]

        for first in range(len(indices)):
            for second in range(
                first + 1,
                len(indices),
            ):
                known_distance = np.linalg.norm(
                    obj[first] - obj[second]
                )

                if np.isclose(
                    known_distance,
                    SQUARE_LENGTH,
                    atol=1e-7,
                ):
                    measured_distance = np.linalg.norm(
                        tri[first] - tri[second]
                    )

                    if np.isfinite(measured_distance):
                        adjacent_distances.append(
                            float(measured_distance)
                        )

    distances = np.asarray(
        adjacent_distances,
        dtype=np.float64,
    )

    if len(distances) == 0:
        raise RuntimeError(
            "No adjacent ChArUco corner pairs "
            "were reconstructed"
        )

    results = {
        "shared_observations_shape": [
            int(value)
            for value in points_2d.shape
        ],
        "validation_stride": validation_stride,
        "rows_before_sampling": original_counts,
        "rows_after_sampling": selected_counts,
        "reprojection": {
            "mean_px": float(
                np.mean(valid_errors)
            ),
            "median_px": float(
                np.median(valid_errors)
            ),
            "p90_px": float(
                np.percentile(valid_errors, 90)
            ),
            "p95_px": float(
                np.percentile(valid_errors, 95)
            ),
            "max_px": float(
                np.max(valid_errors)
            ),
        },
        "scale": {
            "pair_count": int(len(distances)),
            "target_mm": SQUARE_LENGTH * 1000,
            "mean_mm": float(
                np.mean(distances) * 1000
            ),
            "median_mm": float(
                np.median(distances) * 1000
            ),
            "std_mm": float(
                np.std(distances) * 1000
            ),
            "p05_mm": float(
                np.percentile(distances, 5) * 1000
            ),
            "p95_mm": float(
                np.percentile(distances, 95) * 1000
            ),
            "median_scale_error_percent": float(
                (
                    np.median(distances)
                    - SQUARE_LENGTH
                )
                / SQUARE_LENGTH
                * 100
            ),
        },
    }

    reprojection = results["reprojection"]
    scale = results["scale"]

    print("\nValidation results")
    print(
        f"Shared observations: "
        f"{points_2d.shape}"
    )
    print(
        f"Mean reprojection: "
        f"{reprojection['mean_px']:.4f} px"
    )
    print(
        f"Median reprojection: "
        f"{reprojection['median_px']:.4f} px"
    )
    print(
        f"p90 reprojection: "
        f"{reprojection['p90_px']:.4f} px"
    )
    print(
        f"p95 reprojection: "
        f"{reprojection['p95_px']:.4f} px"
    )
    print(
        f"Maximum reprojection: "
        f"{reprojection['max_px']:.4f} px"
    )

    print("\nScale validation")
    print(
        f"Target: "
        f"{scale['target_mm']:.3f} mm"
    )
    print(
        f"Median: "
        f"{scale['median_mm']:.3f} mm"
    )
    print(
        f"Standard deviation: "
        f"{scale['std_mm']:.3f} mm"
    )
    print(
        f"p05-p95: "
        f"{scale['p05_mm']:.3f}-"
        f"{scale['p95_mm']:.3f} mm"
    )
    print(
        f"Median scale error: "
        f"{scale['median_scale_error_percent']:.3f}%"
    )

    return results


def check_quality(
    extrinsic_error: float,
    validation: dict[str, Any],
    max_median_reprojection: float,
    max_p90_reprojection: float,
    max_scale_error_percent: float,
) -> None:
    median_reprojection = validation[
        "reprojection"
    ]["median_px"]

    p90_reprojection = validation[
        "reprojection"
    ]["p90_px"]

    scale_error = abs(
        validation["scale"][
            "median_scale_error_percent"
        ]
    )

    problems = []

    if extrinsic_error > 3.0:
        problems.append(
            f"extrinsic calibration error is "
            f"{extrinsic_error:.3f} px"
        )

    if (
        median_reprojection
        > max_median_reprojection
    ):
        problems.append(
            f"median reprojection error is "
            f"{median_reprojection:.3f} px"
        )

    if p90_reprojection > max_p90_reprojection:
        problems.append(
            f"p90 reprojection error is "
            f"{p90_reprojection:.3f} px"
        )

    if scale_error > max_scale_error_percent:
        problems.append(
            f"absolute median scale error is "
            f"{scale_error:.3f}%"
        )

    if problems:
        formatted = "\n".join(
            f"- {problem}"
            for problem in problems
        )

        raise RuntimeError(
            "Calibration completed but failed the configured "
            f"quality thresholds:\n{formatted}\n\n"
            "The existing root calibration.toml was not replaced."
        )


def publish_calibration(
    root: Path,
    session_calibration_path: Path,
) -> Path:
    destination = root / "calibration.toml"

    if destination.exists():
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        backup = root / (
            f"calibration_backup_{timestamp}.toml"
        )

        shutil.copy2(
            destination,
            backup,
        )

        print(
            f"Previous root calibration backed up to: "
            f"{backup}"
        )

    shutil.copy2(
        session_calibration_path,
        destination,
    )

    print(
        f"Published validated calibration to: "
        f"{destination}"
    )

    return destination


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Align a five-camera FFmpeg session, solve "
            "fixed-intrinsics extrinsics, validate the "
            "calibration, and publish calibration.toml."
        )
    )

    parser.add_argument(
        "--session",
        required=True,
        help=(
            "Session folder name or absolute path, e.g. "
            "extrinsics_20260731_141500"
        ),
    )

    parser.add_argument(
        "--root",
        default=str(
            Path.home()
            / "Downloads"
            / "cv-hand-main"
        ),
        help="Project root directory",
    )

    parser.add_argument(
        "--intrinsics",
        default=None,
        help=(
            "Intrinsic TOML path. Defaults to "
            "<root>/intrinsics.toml or "
            "<root>/calibration/intrinsics.toml"
        ),
    )

    parser.add_argument(
        "--validation-stride",
        type=int,
        default=10,
        help=(
            "Use every Nth detected board row during "
            "validation. Use 1 for exhaustive validation."
        ),
    )

    parser.add_argument(
        "--overwrite-aligned",
        action="store_true",
        help="Regenerate existing aligned videos",
    )

    parser.add_argument(
        "--max-median-reprojection",
        type=float,
        default=2.0,
        help="Maximum accepted median reprojection error",
    )

    parser.add_argument(
        "--max-p90-reprojection",
        type=float,
        default=4.0,
        help="Maximum accepted p90 reprojection error",
    )

    parser.add_argument(
        "--max-scale-error-percent",
        type=float,
        default=2.0,
        help="Maximum accepted absolute median scale error",
    )

    return parser.parse_args()


def resolve_intrinsics_path(
    root: Path,
    argument: str | None,
) -> Path:
    if argument is not None:
        path = Path(argument).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(path)

        return path

    candidates = [
        root / "intrinsics.toml",
        root / "calibration" / "intrinsics.toml",
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find intrinsics.toml. Checked:\n"
        + "\n".join(
            str(path)
            for path in candidates
        )
    )


def main() -> None:
    args = parse_arguments()

    root = Path(
        args.root
    ).expanduser().resolve()

    session_argument = Path(
        args.session
    ).expanduser()

    if session_argument.is_absolute():
        session_path = session_argument.resolve()
    else:
        session_path = (
            root / session_argument
        ).resolve()

    if not session_path.exists():
        raise FileNotFoundError(
            f"Session directory does not exist: "
            f"{session_path}"
        )

    if args.validation_stride < 1:
        raise ValueError(
            "--validation-stride must be at least 1"
        )

    intrinsics_path = resolve_intrinsics_path(
        root,
        args.intrinsics,
    )

    results_dir = session_path / "results"
    results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Five-camera extrinsic recalibration")
    print(f"Project root: {root}")
    print(f"Session: {session_path}")
    print(f"Intrinsics: {intrinsics_path}")
    print(f"OpenCV: {cv2.__version__}")

    raw_videos, logs, metadata = verify_inputs(
        session_path
    )

    start_times, trims, duration = (
        compute_alignment(
            logs,
            metadata,
        )
    )

    aligned_videos, aligned_frame_count = (
        align_videos(
            session_path,
            raw_videos,
            trims,
            duration,
            args.overwrite_aligned,
        )
    )

    cgroup, extrinsic_error, calibration_path = (
        solve_extrinsics(
            intrinsics_path,
            aligned_videos,
            results_dir,
        )
    )

    validation = validate_calibration(
        cgroup,
        aligned_videos,
        args.validation_stride,
    )

    check_quality(
        extrinsic_error,
        validation,
        args.max_median_reprojection,
        args.max_p90_reprojection,
        args.max_scale_error_percent,
    )

    published_path = publish_calibration(
        root,
        calibration_path,
    )

    summary = {
        "created_at": datetime.now().isoformat(),
        "session": str(session_path),
        "intrinsics": str(intrinsics_path),
        "session_calibration": str(calibration_path),
        "published_calibration": str(
            published_path
        ),
        "fps": FPS,
        "resolution": [WIDTH, HEIGHT],
        "aligned_duration_seconds": duration,
        "aligned_frame_count": aligned_frame_count,
        "avfoundation_start_times": start_times,
        "front_trim_seconds": trims,
        "extrinsic_calibration_error_px": (
            extrinsic_error
        ),
        "validation": validation,
    }

    summary_path = (
        results_dir
        / "recalibration_summary.json"
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("CALIBRATION PASSED")
    print("=" * 72)
    print(
        f"Published calibration: "
        f"{published_path}"
    )
    print(
        f"Session results: "
        f"{results_dir}"
    )
    print(
        f"Summary: "
        f"{summary_path}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nInterrupted by user.",
            file=sys.stderr,
        )
        raise SystemExit(130)
    except Exception as exc:
        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
