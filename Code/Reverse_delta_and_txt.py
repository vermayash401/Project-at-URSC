def delta_binary_to_frames(in_bin, out_bin, frame_size=256):
    with open(in_bin, "rb") as f_in, open(out_bin, "wb") as f_out:
        prev = None

        while True:
            chunk = f_in.read(frame_size)
            if not chunk:
                break

            current = list(chunk)

            if prev is None:
                # first frame is raw
                f_out.write(bytes(current))
                prev = current
            else:
                reconstructed = []
                for c, p in zip(current, prev):
                    value = (p + c) & 0xFF   # reverse delta
                    reconstructed.append(value)

                f_out.write(bytes(reconstructed))
                prev = reconstructed

def binary_to_txt_hex(in_bin, out_txt, frame_size=256):
    with open(in_bin, "rb") as f_in, open(out_txt, "w", encoding="utf-8") as f_out:
        while True:
            chunk = f_in.read(frame_size)
            if not chunk:
                break

            # Convert bytes to 2-digit uppercase hex
            hex_values = [f"{b:02X}" for b in chunk]

            # Write one frame per line
            f_out.write(" ".join(hex_values) + "\n")


delta_binary_to_frames(
    "D:/coding programs or libraries/libaec-1.1.5/libaec-1.1.5/build/src/recovered_delta.bin",
    "recovered_original.bin")

binary_to_txt_hex(
    "recovered_original.bin",
    "recovered_original.txt")
