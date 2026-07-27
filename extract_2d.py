import cv2
import h5py
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import pandas as pd

BODY_PARTS = [
    "wrist",
    "thumb_cmc",
    "thumb_mcp",
    "thumb_ip",
    "thumb_tip",
    "index_finger_mcp",
    "index_finger_pip",
    "index_finger_dip",
    "index_finger_tip",
    "middle_finger_mcp",
    "middle_finger_pip",
    "middle_finger_dip",
    "middle_finger_tip",
    "ring_finger_mcp",
    "ring_finger_pip",
    "ring_finger_dip",
    "ring_finger_tip",
    "pinky_mcp",
    "pinky_pip",
    "pinky_dip",
    "pinky_tip",
]

MODEL_PATH = "hand_landmarker.task"
videos = ["2026-07-11 18-14-24_A",
          "2026-07-11 18-14-24_B", 
          "2026-07-11 18-14-24_C", 
          "2026-07-11 18-14-24_D", 
          "2026-07-11 18-14-24_E"]

for video in videos:
    output_path = f"{video}_keypoints.h5"
    video_path = f"hand_videos/{video}.mov"
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
    )

    rows = []
    frame_index = 0

    with vision.HandLandmarker.create_from_options(options) as detector:
        while True:
            success, frame = cap.read()

            if not success:
                break

            timestamp_ms = round(frame_index * 1000 / fps)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb_frame,
            )

            result = detector.detect_for_video(
                mp_image,
                timestamp_ms,
            )

            # One frame contains:
            # x, y, likelihood for each of the 21 hand landmarks.

            row = np.full(21 * 3, np.nan, dtype=np.float32)

            if result.hand_landmarks:
                for joint_index, landmark in enumerate(
                    result.hand_landmarks[0]
                ):

                    column = joint_index * 3
                    row[column] = landmark.x * width
                    row[column + 1] = landmark.y * height
                    
                    # MediaPipe does not expose a separate confidence
                    # score for each individual landmark.
                    row[column + 2] = 1.0

            rows.append(row)
            frame_index += 1

    cap.release()

    columns = pd.MultiIndex.from_product(
        [
            BODY_PARTS,
            ["x", "y", "likelihood"],
        ],

        names=[
            "bodyparts",
            "coords",
        ],

    )

    dataframe = pd.DataFrame(
        rows,
        columns=columns,
    )

    dataframe.to_hdf(
        output_path,
        key="poses",
        mode="w",
    )

    print(f"Saved {len(dataframe)} frames to {output_path}")