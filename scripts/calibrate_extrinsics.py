from pathlib import Path
import numpy as np

from aniposelib.boards import CharucoBoard
from aniposelib.cameras import CameraGroup


ROOT = Path.home() / "Downloads" / "cv-hand-main"
SESSION = ROOT / "extrinsics_20260727_142406"

INTRINSICS_PATH = ROOT / "intrinsics.toml"
OUTPUT_PATH = ROOT / "calibration.toml"

VIDEOS = [
    [str(SESSION / f"aligned/cam{i}.mkv")]
    for i in range(5)
]

BOARD = CharucoBoard(
    squaresX=7,
    squaresY=10,
    square_length=0.024,
    marker_length=0.018,
    marker_bits=4,
    dict_size=50,
)


def main():
    cgroup = CameraGroup.load(str(INTRINSICS_PATH))

    matrices_before = [
        camera.get_camera_matrix().copy()
        for camera in cgroup.cameras
    ]

    distortions_before = [
        camera.get_distortions().copy()
        for camera in cgroup.cameras
    ]

    error, all_rows = cgroup.calibrate_videos(
        VIDEOS,
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

    print(f"\nFinal calibration error: {error:.4f} px")

    for index, camera in enumerate(cgroup.cameras):
        if not np.array_equal(
            matrices_before[index],
            camera.get_camera_matrix(),
        ):
            raise RuntimeError(
                f"cam{index}: intrinsic matrix changed"
            )

        if not np.array_equal(
            distortions_before[index],
            camera.get_distortions(),
        ):
            raise RuntimeError(
                f"cam{index}: distortion changed"
            )

    cgroup.dump(str(OUTPUT_PATH))

    print(f"Saved final calibration to: {OUTPUT_PATH}")

    for index, camera in enumerate(cgroup.cameras):
        print(f"\ncam{index}")
        print("rotation:", camera.get_rotation())
        print("translation:", camera.get_translation())


if __name__ == "__main__":
    main()
