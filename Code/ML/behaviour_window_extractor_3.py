from telemetry_parser_2 import parse_telemetry

def extract_behaviour_windows(file_path, window_size):
    window = []

    for payload in parse_telemetry(file_path):
        window.append(payload)

        if len(window) == window_size:
            yield window
            window = []  #reset for next window


if __name__ == "__main__":
    TELEMETRY_FILE = "telemetry_dataset.hex"
    WINDOW_SIZE = 16

    bw_count = 0

    for bw in extract_behaviour_windows(TELEMETRY_FILE, WINDOW_SIZE):
        print(f"Behaviour Window {bw_count}:")
        for frame in bw:
            print(frame)
        print("-" * 40)

        bw_count += 1
        if bw_count == 45002:
            break