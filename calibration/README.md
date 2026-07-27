# Five-Camera Calibration

## Hardware

- 5 Logitech Brio webcams
- Resolution: 1920 x 1080
- Capture rate: 30 fps
- Capture backend: FFmpeg with AVFoundation
- Calibration and triangulation: Aniposelib 0.8.0

## ChArUco board

- 7 x 10 squares
- Square length: 24 mm
- Marker length: 18 mm
- Dictionary: DICT_4X4_50

## Intrinsic calibration results

| Camera | RMS reprojection error |
|---|---:|
| cam0 | 0.3705 px |
| cam1 | 0.5193 px |
| cam2 | 0.4372 px |
| cam3 | 0.4894 px |
| cam4 | 0.4133 px |

## Extrinsic calibration

Final extrinsic calibration error:

- 1.0325 px

## Independent validation

- Mean reprojection error: 0.9995 px
- Median reprojection error: 0.7738 px
- p90 reprojection error: 2.0214 px
- p95 reprojection error: 2.6566 px

## Scale validation

- Target adjacent-corner distance: 24.000 mm
- Mean reconstructed distance: 23.989 mm
- Median reconstructed distance: 23.992 mm
- Standard deviation: 0.146 mm
- Median scale error: -0.033%

## Camera mapping for calibration session

- cam0: physical camera C
- cam1: physical camera E
- cam2: physical camera D
- cam3: physical camera B
- cam4: physical camera A

AVFoundation indices are not assumed to be permanent. Camera identities must be verified at the start of each capture session.
