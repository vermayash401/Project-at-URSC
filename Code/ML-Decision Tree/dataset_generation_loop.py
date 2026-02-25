import csv
from feature_extraction import compute_window_features
from label_generator import best_strategy_for_window
WINDOW_SIZE = 32


def generate_ml_dataset(frames,
                        aec_compress_func,
                        output_csv="ml_dataset.csv"):
    """
    Builds ML dataset using window-by-window processing.

    Parameters
    ----------
    frames : list[list[str]]
        Full telemetry stream (hex frames)

    aec_compress_func : function
        Your existing AEC compressor wrapper:
        (in_bin_path, out_aec_path) -> None

    output_csv : str
        Output dataset file
    """

    dataset_rows = []
    current_window = []
    prev_window = None

    window_count = 0

    for frame in frames:
        current_window.append(frame)

        # -------------------------------------------------
        # Process when window is full
        # -------------------------------------------------
        if len(current_window) == WINDOW_SIZE:

            # ===== Step 1: compute features =====
            F1, F2, F3, F4 = compute_window_features(
                current_window,
                prev_window
            )

            # ===== Step 2: compute ground-truth label =====
            label, CR_seq, CR_master = best_strategy_for_window(
                current_window,
                prev_window,
                aec_compress_func
            )

            # ===== Step 3: store row =====
            dataset_rows.append([F1, F2, F3, F4, label])

            window_count += 1
            if window_count % 100 == 0:
                print(f"Processed windows: {window_count}")

            # ===== Step 4: slide window (non-overlapping) =====
            prev_window = current_window
            current_window = []

    # -------------------------------------------------
    # Save dataset
    # -------------------------------------------------
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seq_zero_ratio",
            "master_zero_ratio",
            "mean_abs_seq_delta",
            "unique_byte_ratio",
            "label"
        ])
        writer.writerows(dataset_rows)

    print("--------------------------------------------------")
    print(f"Dataset saved: {output_csv}")
    print(f"Total samples: {len(dataset_rows)}")
    print("--------------------------------------------------")

    return dataset_rows