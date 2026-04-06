import socket
import struct
import time

PORT = 6000
TX_CHUNK_SIZE = 120
UDP_MAGIC = 0x43534653
UDP_HEADER_FMT = "<IHHHH"
UDP_HEADER_SIZE = struct.calcsize(UDP_HEADER_FMT)
UDP_PACKET_SIZE = UDP_HEADER_SIZE + TX_CHUNK_SIZE
MAX_BATCH_SIZE = 65535

server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind(("0.0.0.0", PORT))
server_sock.listen(1)

batches = {}

last_packet_time = time.time()
last_warning_time = 0
warning_interval = 10
idle_start = None


def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


print(f"{ts()} Listening for NASA cFS telemetry on TCP {PORT}...")


def print_idle_status(now):
    global last_warning_time, warning_interval

    if now - last_warning_time >= warning_interval:
        print(f"{ts()} [WARN] No telemetry for {int(now - idle_start)} seconds")
        print_incomplete_batches()
        last_warning_time = now
        warning_interval += 10


def print_incomplete_batches():
    if not batches:
        print(f"{ts()} [INFO] No incomplete batches buffered")
        return

    for batch_id in sorted(batches):
        state = batches[batch_id]
        print(
            f"{ts()} [INFO] Incomplete batch {batch_id}: "
            f"{state['received_bytes']} / {state['total_size']} bytes received, "
            f"{len(state['received_offsets'])} chunk(s)"
        )


def recv_exact(sock, size):
    data = bytearray()

    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data.extend(chunk)

    return bytes(data)


def get_batch_state(batch_id, total_size):
    state = batches.get(batch_id)

    if state is None or state["total_size"] != total_size:
        state = {
            "total_size": total_size,
            "data": bytearray(total_size),
            "received_offsets": set(),
            "received_bytes": 0,
        }
        batches[batch_id] = state

    return state


while True:
    print(f"{ts()} Waiting for TCP client...")
    conn, addr = server_sock.accept()
    conn.settimeout(1.0)
    print(f"{ts()} TCP client connected from {addr[0]}:{addr[1]}")

    try:
        while True:
            try:
                data = recv_exact(conn, UDP_PACKET_SIZE)
                if data is None:
                    print(f"{ts()} [WARN] TCP client disconnected")
                    break

                now = time.time()
                last_packet_time = now
                idle_start = None
                warning_interval = 10

                print(f"{ts()} [RX] Packet received: {len(data)} bytes")

                magic, batch_id, chunk_offset, total_size, chunk_size = struct.unpack(
                    UDP_HEADER_FMT, data[:UDP_HEADER_SIZE]
                )
                chunk = data[UDP_HEADER_SIZE:]

                print(f"{ts()} Telemetry chunk bytes: {chunk_size}")

                if magic != UDP_MAGIC:
                    print(f"{ts()} [WARN] Invalid packet magic: 0x{magic:08X}")
                    continue
                if chunk_size == 0:
                    continue
                if chunk_size > TX_CHUNK_SIZE:
                    print(f"{ts()} [WARN] Invalid chunk size: {chunk_size}")
                    continue
                if total_size == 0 or total_size > MAX_BATCH_SIZE:
                    print(f"{ts()} [WARN] Invalid batch size: {total_size}")
                    continue
                if chunk_offset + chunk_size > total_size:
                    print(
                        f"{ts()} [WARN] Invalid chunk bounds: offset={chunk_offset}, "
                        f"chunk={chunk_size}, total={total_size}"
                    )
                    continue

                state = get_batch_state(batch_id, total_size)

                if chunk_offset not in state["received_offsets"]:
                    state["data"][chunk_offset:chunk_offset + chunk_size] = chunk[:chunk_size]
                    state["received_offsets"].add(chunk_offset)
                    state["received_bytes"] += chunk_size

                if state["received_bytes"] >= total_size:
                    filename = f"received_batch_{batch_id}.bin"

                    with open(filename, "wb") as f:
                        f.write(state["data"])

                    print(f"\n{ts()} Batch {batch_id} received")
                    print(f"{ts()} Size: {total_size} bytes")
                    print(f"{ts()} Master Frames: 4")
                    print("")

                    del batches[batch_id]
                else:
                    print(
                        f"{ts()} [INFO] Batch {batch_id} progress: "
                        f"{state['received_bytes']} / {state['total_size']} bytes"
                    )

            except socket.timeout:
                now = time.time()

                if idle_start is None:
                    idle_start = now

                if now - idle_start >= 5:
                    print_idle_status(now)

    finally:
        conn.close()
