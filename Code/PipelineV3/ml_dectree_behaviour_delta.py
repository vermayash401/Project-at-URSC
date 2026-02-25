
WINDOW_SIZE = 32

BYPASS = 0
SEQUENTIAL = 1
MASTER = 2


def behaviour_selector(F1, F2, F3, F4):
    """
    Frozen ML decision tree (no sklearn).
    """

    # --- learned thresholds ---
    if (F2 <= 0.42) and (F1 <= 0.44):
        return BYPASS
    elif F1 > 0.44:
        return SEQUENTIAL
    else:
        return MASTER


def wrapped_delta(curr, ref):
    return [(c - r) & 0xFF for c, r in zip(curr, ref)]


def frames_to_delta_ml(frames, out_bin, compute_window_features):
    """
    ML-driven adaptive delta encoder.

    Parameters
    ----------
    frames : list[list[str]]
    out_bin : output binary path
    compute_window_features : your existing function
    """

    with open(out_bin, "wb") as f:

        prev_frame = None
        master_refs = [None] * 32

        window = []
        prev_window = None

        frame_index = 0
        current_mode = SEQUENTIAL  # default safe mode

        for frame in frames:

            current_int = [int(b, 16) for b in frame]
            slot = frame_index % 32

            window.append(frame)

            # -------------------------------------------------
            # When window completes → run ML selector
            # -------------------------------------------------
            if len(window) == WINDOW_SIZE:

                F1, F2, F3, F4 = compute_window_features(
                    window,
                    prev_window
                )

                current_mode = behaviour_selector(F1, F2, F3, F4)

                prev_window = window
                window = []

            # -------------------------------------------------
            # First frame always raw
            # -------------------------------------------------
            if prev_frame is None:
                f.write(bytes([BYPASS]))
                f.write(bytes(current_int))
                prev_frame = current_int
                master_refs[slot] = current_int.copy()
                frame_index += 1
                continue

            # -------------------------------------------------
            # Apply selected mode
            # -------------------------------------------------
            if current_mode == BYPASS:
                out_bytes = current_int

            elif current_mode == SEQUENTIAL:
                out_bytes = wrapped_delta(current_int, prev_frame)

            else:  # MASTER
                ref = master_refs[slot]
                if ref is None:
                    ref = prev_frame
                out_bytes = wrapped_delta(current_int, ref)

            f.write(bytes([current_mode]))
            f.write(bytes(out_bytes))

            # update state
            prev_frame = current_int
            master_refs[slot] = current_int.copy()
            frame_index += 1