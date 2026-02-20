def delta_bin_to_txt_hex(in_bin, out_txt, frame_size=256, delta_mode="sequential"):
    if delta_mode not in ("sequential", "master_aligned"):
        raise ValueError("delta_mode must be 'sequential' or 'master_aligned'")

    with open(in_bin, "rb") as f_in, open(out_txt, "w", encoding="utf-8") as f_out:
        prev = None
        master_refs = [None] * 32
        frame_idx = 0

        while True:
            chunk = f_in.read(frame_size)
            if not chunk:
                break
            if len(chunk) != frame_size:
                raise ValueError(f"Incomplete frame: got {len(chunk)} bytes, expected {frame_size}")

            current = list(chunk)

            if prev is None:
                # first frame is raw
                reconstructed = current
            else:
                if delta_mode == "master_aligned":
                    slot = frame_idx % 32
                    ref = master_refs[slot] if master_refs[slot] is not None else prev
                else:
                    ref = prev

                # reverse delta: reconstructed = reference + delta
                reconstructed = [((r + d) & 0xFF) for d, r in zip(current, ref)]

            # write reconstructed frame directly to txt
            f_out.write(" ".join(f"{b:02X}" for b in reconstructed) + "\n")
            master_refs[frame_idx % 32] = reconstructed.copy()
            prev = reconstructed
            frame_idx += 1
    print("TELEMETRY RECONSTRUCTED to", out_txt)
    print("------------------------------------------------------------------------")

def decompressed_reconstruction(inbin, outtxt, delta_mode="sequential"):
    delta_bin_to_txt_hex(inbin, outtxt, delta_mode=delta_mode)

#delta_bin_to_txt_hex("spacecraft_frames6_delta_decompmessed.bin","spacecraft_frames6_reconstructed.txt",)
