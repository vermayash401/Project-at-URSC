# compare_frames.py
from __future__ import annotations

import hashlib
import os
from typing import Iterator, Tuple

ORIGINAL_FILE = "spacecraft_frames6.txt"
RECON_FILE = "spacecraft_frames6_reconstructed.txt"
MAX_MISMATCH_REPORTS = 20


def norm_line(line: str) -> str:
    # normalize spacing/case so harmless formatting differences are ignored
    return " ".join(line.strip().upper().split())


def iter_lines(path: str) -> Iterator[str]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield norm_line(line)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compare_files(a_path: str, b_path: str) -> Tuple[bool, int]:
    a_iter = iter_lines(a_path)
    b_iter = iter_lines(b_path)

    line_no = 0
    mismatches = 0

    while True:
        try:
            a = next(a_iter)
            a_end = False
        except StopIteration:
            a_end = True
            a = None

        try:
            b = next(b_iter)
            b_end = False
        except StopIteration:
            b_end = True
            b = None

        if a_end and b_end:
            break

        line_no += 1

        if a_end != b_end or a != b:
            mismatches += 1
            if mismatches <= MAX_MISMATCH_REPORTS:
                print(f"\nMismatch at frame(line) {line_no}:")
                print(f"  original     : {a}")
                print(f"  reconstructed: {b}")

                # byte-level location (if both exist)
                if a is not None and b is not None:
                    a_parts = a.split()
                    b_parts = b.split()
                    m = min(len(a_parts), len(b_parts))
                    idx = next((i for i in range(m) if a_parts[i] != b_parts[i]), None)
                    if idx is not None:
                        print(
                            f"  first differing byte index: {idx} "
                            f"(orig={a_parts[idx]}, recon={b_parts[idx]})"
                        )
                    elif len(a_parts) != len(b_parts):
                        print(
                            f"  byte count differs: orig={len(a_parts)}, recon={len(b_parts)}"
                        )

        #if line_no % 50000 == 0:
            #print(f"\rCompared {line_no} lines...", end="", flush=True)

    #if line_no >= 50000:
        #print()

    return mismatches == 0, line_no


def compare (ORIGINAL_FILE, RECON_FILE, MAX_MISMATCH_REPORTS=20):
    #print(f"Original file     : {ORIGINAL_FILE}")
    #print(f"Reconstructed file: {RECON_FILE}")
    #print(f"Sizes (bytes)     : {os.path.getsize(ORIGINAL_FILE):,} vs {os.path.getsize(RECON_FILE):,}")

    # optional: raw file hash (strict byte-for-byte, includes whitespace differences)
    #print(f"SHA256 original   : {file_sha256(ORIGINAL_FILE)}")
    #print(f"SHA256 recon      : {file_sha256(RECON_FILE)}")

    ok, total = compare_files(ORIGINAL_FILE, RECON_FILE)

    #print(f"\nTotal compared lines: {total:,}")
    if ok:
        print("Reconstruced and Original telemetry: MATCH (normalized frame content identical)")
    else:
        print("Reconstructed and Original telemetry: NOT MATCH")
        print(f"Reported up to {MAX_MISMATCH_REPORTS} mismatches above.")
    print("------------------------------------------------------------------------")
