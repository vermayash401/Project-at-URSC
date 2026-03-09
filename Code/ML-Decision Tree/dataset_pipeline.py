from dataset_generation_loop import generate_ml_dataset
from string_hex_stream_with_delta_not_random import generate_month_frames
from string_hex_stream_with_delta_not_random import generate_master_correlated_frames
import csv
import os
import tempfile
from collections import Counter
from huffman_coding import huffman_encode_file
from arithmetic_coding import arithmetic_encode
from rice_encoding import rice_encode_rle_adaptive_mean
from ZRLE import zero_rle_encode


# source_mode: "simulate" or "txt"
SOURCE_MODE = "simulate"
INPUT_TXT_FILE = "original_telemetry31.txt"

# Compression method after delta+zrle:
# "rice_stream_mean", "huffman", "arithmetic", "zrle_only"
COMPRESSION_METHOD = "rice_stream_mean"
OUTPUT_CSV = "ml_dectree_dataset_rice_stream.csv"


def load_frames_from_txt(txt_file):
    frames = []
    with open(txt_file, "r", encoding="utf-8") as fin:
        for line_no, line in enumerate(fin, start=1):
            parts = line.strip().split()
            if not parts:
                continue
            if len(parts) != 256:
                raise ValueError(f"Line {line_no}: expected 256 bytes, got {len(parts)}")
            frames.append(parts)
    if not frames:
        raise ValueError("No frames found in input txt")
    return frames


def generate_simulated_frames(days=6):
    #1 million frames of telemtery almost = 6 DAYS-------2 days each mode- bypass,sequential,master
    max_changes = [1, 2, 4, 8, 16, 32, 64]
    l = len(max_changes)
    each_regime_data_duration_in_days = days / (2 * (l + 1))

    frames_same = generate_month_frames(each_regime_data_duration_in_days, 0, [0, 10, 0])
    frames_random = generate_month_frames(each_regime_data_duration_in_days, 0, [0, 0, 10])
    frames_related = []

    for i in max_changes:
        frames_master = generate_master_correlated_frames(each_regime_data_duration_in_days, i, [0, 10, 0])
        frames_seq = generate_month_frames(each_regime_data_duration_in_days, i, [0, 10, 0])
        frames_related.extend(frames_master)
        frames_related.extend(frames_seq)

    frames = frames_same + frames_related + frames_random
    print("frames_same:", len(frames_same))
    print("frames_related:", len(frames_related))
    print("frames_random:", len(frames_random))
    return frames


def delta_zrle_compress_method(in_delta_bin_path, out_cmp_path, compression_method=COMPRESSION_METHOD):
    """
    Master compressor used by generate_ml_dataset.
    Input is delta binary (produced inside label_generator).
    This function applies:
        delta (already done by caller) + zrle + compression_method
    """
    with tempfile.TemporaryDirectory() as tmp:
        zrle_path = os.path.join(tmp, "delta_zrle.bin")
        zero_rle_encode(in_delta_bin_path, zrle_path)

        if compression_method == "rice_stream_mean":
            rice_encode_rle_adaptive_mean(zrle_path, out_cmp_path, window_size=4096)
        elif compression_method == "huffman":
            huffman_encode_file(zrle_path, out_cmp_path)
        elif compression_method == "arithmetic":
            arithmetic_encode(zrle_path, out_cmp_path)
        elif compression_method == "zrle_only":
            with open(zrle_path, "rb") as f_in, open(out_cmp_path, "wb") as f_out:
                f_out.write(f_in.read())
        else:
            raise ValueError(f"Unknown compression_method: {compression_method}")


def print_dataset_stats(csv_path):
    label_counter = Counter()
    total = 0

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label_counter[int(row["label"])] += 1
            total += 1

    print("\nDATASET SUMMARY")
    print(f"Total samples: {total}")
    print(f"BYPASS (0): {label_counter[0]}")
    print(f"SEQUENTIAL (1): {label_counter[1]}")
    print(f"MASTER (2): {label_counter[2]}")


if SOURCE_MODE == "txt":
    frames = load_frames_from_txt(INPUT_TXT_FILE)
else:
    frames = generate_simulated_frames(days=6)

print(f"Total frames loaded: {len(frames)}")

generate_ml_dataset(
    frames,
    lambda in_bin, out_bin: delta_zrle_compress_method(in_bin, out_bin, COMPRESSION_METHOD),
    OUTPUT_CSV,
)

print_dataset_stats(OUTPUT_CSV)

