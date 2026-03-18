import csv

from behaviour_window_extractor_3 import extract_behaviour_windows
from feature_extraction_4 import extract_features

def build_dataset(telemetry_file, window_size, total_frames, frames_per_mode, output_csv):
    """
    Streams windows -> features -> labeled rows into a CSV file.

    Assumes extract_behaviour_windows(...) yields NON-OVERLAPPING windows,
    each spanning `window_size` frames.
    """
    if frames_per_mode <= 0:
        raise ValueError("frames_per_mode must be > 0")
    if total_frames <= 0:
        raise ValueError("total_frames must be > 0")
    if window_size <= 0:
        raise ValueError("window_size must be > 0")

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for window_index, window in enumerate(
            extract_behaviour_windows(telemetry_file, window_size)
        ):
            # Non-overlapping window start frame
            start_frame = window_index * window_size

            # Optional guard: skip windows that start beyond available frames
            if start_frame >= total_frames:
                break

            label = start_frame // frames_per_mode
            label = max(0, min(3, label))  # clamp to [0, 3]

            features = extract_features(window)
            writer.writerow([*features, label])


if __name__ == "__main__":
    build_dataset(
        telemetry_file="telemetry_dataset.hex",
        window_size=16,
        total_frames=2592000,
        frames_per_mode=648000,
        output_csv="ml_dataset.csv"
    )
