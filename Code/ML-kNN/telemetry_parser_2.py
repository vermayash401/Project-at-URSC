# from 1)
#header =4 bytes
#frame id = 4 bytes
#payload = 5 bytes or configurable
#footer = 2 bytes

headerlen=4
footerlen=2
frameidlen=4
payloadlen=5
framelen=headerlen+frameidlen+payloadlen+footerlen

def parse_telemetry(file_path):
    with open(file_path, 'r') as file:

        for frame_num, frame in enumerate(file, start=1):
            frame=frame.strip()

            if not frame:
                continue
            try:
                frame_bytes = [int(x, 16) for x in frame.split()]
            except ValueError:
                raise ValueError(f"Invalid hex data at line {frame_num}")
            
            payload_start=headerlen+frameidlen
            payload_end=payload_start+payloadlen
            payload=frame_bytes[payload_start:payload_end]

            yield payload
        

if __name__ == "__main__":
    telemetry_file = "telemetry_dataset.hex"

    count = 0
    for payload in parse_telemetry(telemetry_file):
        print(payload)
        count += 1
        if count == 648010:
            break