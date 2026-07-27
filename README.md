# Motion Capture

Five-camera markerless hand-pose estimation system for rheumatoid arthritis assessment.

## Current pipeline

1. Capture synchronized video from five Logitech Brio cameras
2. Estimate per-camera intrinsic calibration using a ChArUco board
3. Estimate fixed-intrinsics multi-camera extrinsics
4. Validate reprojection accuracy and physical scale
5. Extract 2D hand landmarks
6. Triangulate 3D hand landmarks
7. Estimate hand and wrist range of motion

## Repository structure

- `scripts/`: calibration, validation, capture, and processing scripts
- `calibration/`: validated camera parameters and calibration results
- `calibration/logs/`: reproducibility logs
- Raw videos and participant data are excluded from Git
