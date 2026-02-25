import tempfile
import os
from AEC import AEC

BYPASS = 0
SEQUENTIAL = 1
MASTER = 2

def AEC_compress_wrapper(in_bin_path, out_aec_path):
    AEC("compress",
        in_bin_path,
        out_aec_path,
        None,
        None)

def best_strategy_for_window(current_window,
                             prev_window,
                             aec_compress_func):
    """
    Determines best compression strategy for a single window.

    Parameters
    ----------
    current_window : list[list[str]]
        32 frames (hex strings)

    prev_window : list[list[str]] or None
        Previous 32-frame window

    aec_compress_func : function
        Your existing AEC compressor wrapper:
        (in_bin_path, out_aec_path) -> None

    Returns
    -------
    label : int
        0=BYPASS, 1=SEQUENTIAL, 2=MASTER

    CR_seq : float
    CR_master : float or None
    """

    FRAME_SIZE = len(current_window[0])

    # -------------------------------------------------
    # Helper: convert hex frames → delta binary file
    # -------------------------------------------------
    def write_delta_file(frames, refs, mode, out_path):
        with open(out_path, "wb") as f:
            prev = None

            for idx, frame in enumerate(frames):
                curr = [int(b, 16) for b in frame]

                if idx == 0 and mode == "sequential":
                    f.write(bytes(curr))
                else:
                    if mode == "sequential":
                        reference = prev
                    elif mode == "master":
                        reference = refs[idx]
                    else:
                        raise ValueError("unknown mode")

                    delta = [(c - r) & 0xFF for c, r in zip(curr, reference)]
                    f.write(bytes(delta))

                prev = curr

    # -------------------------------------------------
    # Create temp files
    # -------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:

        # ===== Sequential candidate =====
        seq_bin = os.path.join(tmp, "seq.bin")
        seq_aec = os.path.join(tmp, "seq.aec")

        write_delta_file(current_window, None, "sequential", seq_bin)
        aec_compress_func(seq_bin, seq_aec)

        raw_size = os.path.getsize(seq_bin)
        seq_size = os.path.getsize(seq_aec)
        CR_seq = raw_size / seq_size if seq_size > 0 else 0.0

        # ===== Master candidate =====
        if prev_window is None:
            CR_master = None
        else:
            master_bin = os.path.join(tmp, "master.bin")
            master_aec = os.path.join(tmp, "master.aec")

            # prepare reference frames
            master_refs = [
                [int(b, 16) for b in frame]
                for frame in prev_window
            ]

            write_delta_file(current_window, master_refs, "master", master_bin)
            aec_compress_func(master_bin, master_aec)

            master_size = os.path.getsize(master_aec)
            CR_master = raw_size / master_size if master_size > 0 else 0.0

    # -------------------------------------------------
    # Decision logic (LOCKED)
    # -------------------------------------------------
    CR_bypass = 1.0
    epsilon = 0.02

    # first-window case
    if CR_master is None:
        if CR_seq <= CR_bypass:
            return BYPASS, CR_seq, CR_master
        return SEQUENTIAL, CR_seq, CR_master

    # both bad
    if CR_seq <= CR_bypass and CR_master <= CR_bypass:
        return BYPASS, CR_seq, CR_master

    # sequential wins
    if (CR_seq > CR_master) and (CR_seq > CR_bypass):
        return SEQUENTIAL, CR_seq, CR_master

    # master wins
    if (CR_master > CR_seq) and (CR_master > CR_bypass):
        return MASTER, CR_seq, CR_master

    # tie-break
    if abs(CR_seq - CR_master) < epsilon:
        return SEQUENTIAL, CR_seq, CR_master

    # fallback
    return SEQUENTIAL if CR_seq >= CR_master else MASTER, CR_seq, CR_master