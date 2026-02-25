def compute_window_features(current_window, prev_window):
    """
    Computes minimal ML feature set for one window.

    Features:
        F1 = sequential_zero_ratio
        F2 = master_zero_ratio
        F3 = mean_abs_sequential_delta
        F4 = unique_byte_ratio
    """

    W = len(current_window)
    FRAME_SIZE = len(current_window[0])

    # -----------------------------
    # Convert hex → int once
    # -----------------------------
    curr_int = [[int(b, 16) for b in frame] for frame in current_window]

    if prev_window is not None:
        prev_int = [[int(b, 16) for b in frame] for frame in prev_window]
    else:
        prev_int = None

    # ============================================================
    # Feature 1 & 3 — Sequential statistics
    # ============================================================

    seq_zero_count = 0
    seq_abs_sum = 0
    seq_total = 0

    for i in range(1, W):
        prev_f = curr_int[i - 1]
        curr_f = curr_int[i]

        for c, p in zip(curr_f, prev_f):
            d = (c - p) & 0xFF

            if d == 0:
                seq_zero_count += 1

            seq_abs_sum += d if d <= 127 else (256 - d)
            seq_total += 1

    if seq_total == 0:
        F1 = 0.0
        F3 = 0.0
    else:
        F1 = seq_zero_count / seq_total
        F3 = seq_abs_sum / seq_total

    # ============================================================
    # Feature 2 — Master-aligned zero ratio
    # ============================================================

    if prev_int is None:
        F2 = 0.0
    else:
        master_zero_count = 0
        master_total = 0

        for k in range(W):
            curr_f = curr_int[k]
            prev_f = prev_int[k]

            for c, p in zip(curr_f, prev_f):
                d = (c - p) & 0xFF
                if d == 0:
                    master_zero_count += 1
                master_total += 1

        F2 = master_zero_count / master_total if master_total else 0.0

    # ============================================================
    # Feature 4 — Unique byte ratio (entropy proxy)
    # ============================================================

    unique_bytes = set()

    for frame in curr_int:
        unique_bytes.update(frame)

    F4 = len(unique_bytes) / 256.0

    return F1, F2, F3, F4