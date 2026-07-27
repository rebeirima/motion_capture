from aniposelib.boards import CharucoBoard

board = CharucoBoard(
    squaresX=7,
    squaresY=10,
    square_length=0.024,
    marker_length=0.018,
    marker_bits=4,
    dict_size=50,
)

rows = board.detect_video(
    "intrinsics_cam0_new.mkv",
    progress=True,
    skip=5,
)

print(f"Detected board observations: {len(rows)}")

obj, img = board.get_all_calibration_points(rows, min_points=12)

print(f"Usable calibration views: {len(obj)}")
