WINDOW_SIZE = 32

BYPASS = 0
SEQUENTIAL = 1
MASTER = 2


def reverse_delta_ml(
    in_bin,
    out_txt,
    compute_window_features=None  # kept only for signature compatibility
):
    """
    Flight-correct reverse delta reconstruction.

    EXPECTED INPUT FORMAT PER FRAME:
        [1 byte mode][256 bytes payload]

    Decoder DOES NOT run ML.
    It follows encoder decisions.
    """

    FRAME_SIZE = 256

    with open(in_bin, "rb") as f_in, open(out_txt, "w") as f_out:

        prev_frame = None
        master_refs = [None] * 32
        frame_index = 0

        while True:

            # -------------------------------------------------
            # Read mode byte (CRITICAL)
            # -------------------------------------------------
            mode_byte = f_in.read(1)
            if not mode_byte:
                break

            current_mode = mode_byte[0]

            # -------------------------------------------------
            # Read frame payload
            # -------------------------------------------------
            chunk = f_in.read(FRAME_SIZE)
            if len(chunk) < FRAME_SIZE:
                break

            current = list(chunk)
            slot = frame_index % 32

            # -------------------------------------------------
            # First frame always raw
            # -------------------------------------------------
            if prev_frame is None:
                reconstructed = current

            else:
                if current_mode == BYPASS:
                    reconstructed = current

                elif current_mode == SEQUENTIAL:
                    reconstructed = [
                        (p + c) & 0xFF
                        for p, c in zip(prev_frame, current)
                    ]

                elif current_mode == MASTER:
                    ref = master_refs[slot]
                    if ref is None:
                        ref = prev_frame

                    reconstructed = [
                        (r + c) & 0xFF
                        for r, c in zip(ref, current)
                    ]

                else:
                    raise ValueError(f"Unknown mode byte: {current_mode}")

            # -------------------------------------------------
            # Write reconstructed frame
            # -------------------------------------------------
            f_out.write(
                " ".join(f"{b:02X}" for b in reconstructed) + "\n"
            )

            # -------------------------------------------------
            # Update state
            # -------------------------------------------------
            prev_frame = reconstructed
            master_refs[slot] = reconstructed.copy()
            frame_index += 1