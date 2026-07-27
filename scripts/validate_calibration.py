from pathlib import Path

import numpy as np

from aniposelib.boards import CharucoBoard, extract_points, merge_rows
from aniposelib.cameras import CameraGroup


ROOT = Path.home() / "Downloads" / "cv-hand-main"
SESSION = ROOT / "extrinsics_20260727_142406"

CALIBRATION_PATH = ROOT / "calibration.toml"

VIDEOS = [
    [str(SESSION / f"aligned/cam{i}.mkv")]
    for i in range(5)
]

SQUARE_LENGTH = 0.024

BOARD = CharucoBoard(
    squaresX=7,
    squaresY=10,
    square_length=SQUARE_LENGTH,
    marker_length=0.018,
    marker_bits=4,
    dict_size=50,
)


def main():
    cgroup = CameraGroup.load(str(CALIBRATION_PATH))

    print("Detecting board observations...")
    all_rows = cgroup.get_rows_videos(
        VIDEOS,
        BOARD,
        verbose=True,
    )

    for camera_index, camera in enumerate(cgroup.cameras):
        all_rows[camera_index] = BOARD.estimate_pose_rows(
            camera,
            all_rows[camera_index],
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

    print("Shared observations shape:", points_2d.shape)

    if points_2d.shape[1] == 0:
        raise RuntimeError(
            "No shared observations found. Check camera order and synchronization."
        )

    points_3d = cgroup.triangulate(points_2d)

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

    print("\nReprojection error")
    print(f"mean:   {np.mean(valid_errors):.4f} px")
    print(f"median: {np.median(valid_errors):.4f} px")
    print(f"p90:    {np.percentile(valid_errors, 90):.4f} px")
    print(f"p95:    {np.percentile(valid_errors, 95):.4f} px")
    print(f"max:    {np.max(valid_errors):.4f} px")

    board_instance_ids = np.asarray(extra["ids"])
    object_points = np.asarray(extra["objp"])

    adjacent_distances = []

    for board_instance in np.unique(board_instance_ids):
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

        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                known_distance = np.linalg.norm(
                    obj[a] - obj[b]
                )

                if np.isclose(
                    known_distance,
                    SQUARE_LENGTH,
                    atol=1e-7,
                ):
                    measured_distance = np.linalg.norm(
                        tri[a] - tri[b]
                    )

                    if np.isfinite(measured_distance):
                        adjacent_distances.append(
                            measured_distance
                        )

    distances = np.asarray(adjacent_distances)

    if len(distances) == 0:
        raise RuntimeError(
            "No reconstructed adjacent board-corner pairs were found."
        )

    print("\nAdjacent ChArUco corner distances")
    print(f"pairs:  {len(distances)}")
    print(f"target: {SQUARE_LENGTH * 1000:.3f} mm")
    print(f"mean:   {np.mean(distances) * 1000:.3f} mm")
    print(f"median: {np.median(distances) * 1000:.3f} mm")
    print(f"std:    {np.std(distances) * 1000:.3f} mm")
    print(
        "p05-p95: "
        f"{np.percentile(distances, 5) * 1000:.3f}-"
        f"{np.percentile(distances, 95) * 1000:.3f} mm"
    )

    scale_error = (
        np.median(distances) - SQUARE_LENGTH
    ) / SQUARE_LENGTH

    print(f"Median scale error: {scale_error * 100:.3f}%")


if __name__ == "__main__":
    main()
