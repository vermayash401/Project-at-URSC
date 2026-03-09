import os
from pathlib import Path

from feature_extraction import compute_window_features
from delta_encoding import frames_to_delta_ml, reverse_delta_ml
from compare_files import compare
from ZRLE import zero_rle_encode, zero_rle_decode
from huffman_coding import huffman_encode_file, huffman_decode_file
from arithmetic_coding import arithmetic_encode, arithmetic_decode
from rice_encoding import rice_encode_rle_adaptive_mean,rice_decode_rle_adaptive

def load_frames_from_txt(txt_file):
    frames=[]
    with open(txt_file, "r", encoding="utf-8") as fin:
        for line_no, line in enumerate(fin, start=1):
            parts=line.strip().split()
            if not parts:
                continue
            if len(parts)!=256:
                raise ValueError(f"Line {line_no}: expected 256 hex bytes, got {len(parts)}")
            frames.append(parts)
    if not frames:
        raise ValueError("Input telemetry txt has no frames")
    return frames

def run_chain(input_txt, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = Path(input_txt)
    base = txt_path.stem

    delta_bin = out_dir / f"{base}_delta.bin"
    rle_bin = out_dir / f"{base}_delta_rle.bin"

    print("Building delta from input txt...")
    frames = load_frames_from_txt(str(txt_path))
    frames_to_delta_ml(frames, str(delta_bin), compute_window_features)

    print("Building ZRLE(delta)...")
    zero_rle_encode(str(delta_bin), str(rle_bin))

    methods = [
        "rice_stream_mean",
        "huffman",
        "arithmetic",
    ]

    for method in methods:
        print(f"\n=== Running {method} on ZRLE(delta) ===")
        compressed = out_dir / f"{base}_delta_zrle_{method}.bin"
        recovered_rle = out_dir / f"{base}_delta_zrle_{method}_recovered_rle.bin"
        recovered_delta = out_dir / f"{base}_delta_zrle_{method}_recovered_delta.bin"
        recovered_txt = out_dir / f"{base}_delta_zrle_{method}_reconstructed.txt"

        if method == "huffman":
            huffman_encode_file(str(rle_bin), str(compressed))
            huffman_decode_file(str(compressed), str(recovered_rle))

        elif method == "arithmetic":
            arithmetic_encode(str(rle_bin), str(compressed))
            arithmetic_decode(str(compressed), str(recovered_rle))

        elif method == "rice_stream_mean":
            rice_encode_rle_adaptive_mean(str(rle_bin), str(compressed), window_size=4096)
            rice_decode_rle_adaptive(str(compressed), str(recovered_rle))

        zero_rle_decode(str(recovered_rle), str(recovered_delta))
        reverse_delta_ml(str(recovered_delta), str(recovered_txt))

        print(f"Comparing final reconstructed txt for {method}:")
        compare(str(txt_path), str(recovered_txt))

    print("\nPipeline complete.")


def main():
    input_txt = str(Path(__file__).resolve().parent.parent / "original_telemetry31.txt")
    out_dir = str(Path(__file__).resolve().parent.parent / "pipelineV4_outputs")
    run_chain(input_txt, out_dir)


if __name__ == "__main__":
    main()
