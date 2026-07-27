from pathlib import Path
import sys

import cv2
import numpy as np

from aniposelib.boards import CharucoBoard, get_video_params
from aniposelib.cameras import Camera, CameraGroup


ROOT = Path.home() / "Downloads" / "cv-hand-main"

VIDEO_PATHS = [
    ROOT / f"intrinsics_cam{i}_new.mkv"
    for i in range(5)
]

OUTPUT_PATH = ROOT / "intrinsics.toml"

BOARD = CharucoBoard(
    squaresX=7,
    squaresY=10,
    square_length=0.024,
    marker_length=0.018,
    marker_bits=4,
    dict_size=50,
)

MIN_CORNERS_PER_VIEW = 12

# Detect every fifth video frame.
DETECTION_SKIP = 5

# Your recordings contain approximately 2,000 usable detections.
# Taking every tenth usable view leaves approximately 200 diverse views.
VIEW_SUBSAMPLE = 10


def per_view_reprojection_errors(
    object_points,
    image_points,
    camera_matrix,
    distortion,
    rvecs,
    tvecs,
):
    errors = []

    for obj, img, rvec, tvec in zip(
        object_points,
        image_points,
        rvecs,
        tvecs,
    ):
        projected, _ = cv2.projectPoints(
            obj,
            rvec,
            tvec,
            camera_matrix,
            distortion,
        )

        observed = img.reshape(-1, 2)
        projected = projected.reshape(-1, 2)

        residual = observed - projected
        rms = np.sqrt(np.mean(np.sum(residual**2, axis=1)))
        errors.append(float(rms))

    return np.asarray(errors)


def calibrate_camera(index, video_path):
    if not video_path.exists():
        raise FileNotFoundError(f"Missing video: {video_path}")

    params = get_video_params(str(video_path))
    width = int(params["width"])
    height = int(params["height"])
    image_size = (width, height)

    print("\n" + "=" * 72)
    print(f"CAMERA INDEX {index}")
    print(f"Video: {video_path.name}")
    print(f"Resolution: {width} x {height}")
    print("=" * 72)

    if image_size != (1920, 1080):
        raise RuntimeError(
            f"cam{index}: expected 1920x1080, received {image_size}"
        )

    rows = BOARD.detect_video(
        str(video_path),
        skip=DETECTION_SKIP,
        progress=True,
    )

    print(f"\nDetected board observations: {len(rows)}")

    object_points_all, image_points_all = (
        BOARD.get_all_calibration_points(
            rows,
            min_points=MIN_CORNERS_PER_VIEW,
        )
    )

    usable_pairs = []

    for obj, img in zip(object_points_all, image_points_all):
        if (
            len(obj) >= MIN_CORNERS_PER_VIEW
            and len(img) >= MIN_CORNERS_PER_VIEW
        ):
            usable_pairs.append(
                (
                    np.ascontiguousarray(obj, dtype=np.float32),
                    np.ascontiguousarray(img, dtype=np.float32),
                )
            )

    print(f"Usable views before subsampling: {len(usable_pairs)}")

    if len(usable_pairs) < 100:
        raise RuntimeError(
            f"cam{index}: only {len(usable_pairs)} usable views. "
            "Do not calibrate this camera yet."
        )

    usable_pairs = usable_pairs[::VIEW_SUBSAMPLE]

    object_points = [pair[0] for pair in usable_pairs]
    image_points = [pair[1] for pair in usable_pairs]

    print(f"Views used for calibration: {len(object_points)}")

    corner_counts = np.asarray(
        [len(points) for points in image_points]
    )

    print(
        "Corners per selected view: "
        f"median={np.median(corner_counts):.0f}, "
        f"min={corner_counts.min()}, "
        f"max={corner_counts.max()}"
    )

    criteria = (
        cv2.TERM_CRITERIA_EPS
        + cv2.TERM_CRITERIA_MAX_ITER,
        200,
        1e-10,
    )

    rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
        objectPoints=object_points,
        imagePoints=image_points,
        imageSize=image_size,
        cameraMatrix=None,
        distCoeffs=None,
        flags=0,
        criteria=criteria,
    )

    distortion = np.asarray(
        distortion,
        dtype=np.float64,
    ).reshape(-1)

    view_errors = per_view_reprojection_errors(
        object_points,
        image_points,
        matrix,
        distortion,
        rvecs,
        tvecs,
    )

    fx = float(matrix[0, 0])
    fy = float(matrix[1, 1])
    cx = float(matrix[0, 2])
    cy = float(matrix[1, 2])

    center_x = (width - 1) / 2
    center_y = (height - 1) / 2

    print("\nIntrinsic calibration results")
    print(f"OpenCV RMS: {rms:.4f} px")
    print(
        "Per-view RMS: "
        f"median={np.median(view_errors):.4f} px, "
        f"p90={np.percentile(view_errors, 90):.4f} px, "
        f"max={np.max(view_errors):.4f} px"
    )
    print(f"fx={fx:.4f}")
    print(f"fy={fy:.4f}")
    print(f"cx={cx:.4f}")
    print(f"cy={cy:.4f}")
    print(f"Default image center=({center_x:.1f}, {center_y:.1f})")
    print(f"Distortion={distortion}")

    if not np.all(np.isfinite(matrix)):
        raise RuntimeError(f"cam{index}: non-finite camera matrix")

    if not np.all(np.isfinite(distortion)):
        raise RuntimeError(
            f"cam{index}: non-finite distortion coefficients"
        )

    if fx <= 0 or fy <= 0:
        raise RuntimeError(f"cam{index}: invalid focal length")

    if np.linalg.norm(distortion) < 1e-8:
        raise RuntimeError(
            f"cam{index}: distortion is effectively zero"
        )

    if (
        np.isclose(cx, center_x, atol=1e-9)
        and np.isclose(cy, center_y, atol=1e-9)
    ):
        raise RuntimeError(
            f"cam{index}: principal point remained exactly at "
            "the default image center"
        )

    if rms > 2.0:
        print(
            "WARNING: RMS exceeds 2 px. Inspect blur, coverage, "
            "board flatness, or outlier views."
        )

    camera = Camera(
        matrix=matrix,
        dist=distortion[:5],
        size=image_size,
        rvec=np.zeros(3),
        tvec=np.zeros(3),
        name=f"cam{index}",
    )

    return camera


def main():
    print(f"Python: {sys.version}")
    print(f"OpenCV: {cv2.__version__}")

    cameras = []

    for index, video_path in enumerate(VIDEO_PATHS):
        cameras.append(
            calibrate_camera(index, video_path)
        )

    group = CameraGroup(cameras)
    group.dump(str(OUTPUT_PATH))

    print("\n" + "=" * 72)
    print(f"Saved intrinsics to: {OUTPUT_PATH}")
    print("=" * 72)

    for index, camera in enumerate(group.cameras):
        matrix = camera.get_camera_matrix()
        distortion = camera.get_distortions()

        print(
            f"cam{index}: "
            f"fx={matrix[0, 0]:.3f}, "
            f"fy={matrix[1, 1]:.3f}, "
            f"cx={matrix[0, 2]:.3f}, "
            f"cy={matrix[1, 2]:.3f}, "
            f"dist={distortion}"
        )


if __name__ == "__main__":
    main()
