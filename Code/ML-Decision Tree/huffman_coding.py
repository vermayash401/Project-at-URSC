import time
from collections import Counter


class BitWriter:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def write_bits(self, value, nbits):
        while nbits > 0:
            space = 8 - self.nbits
            take = min(space, nbits)
            shift = nbits - take
            chunk = (value >> shift) & ((1 << take) - 1)
            self.buffer = (self.buffer << take) | chunk
            self.nbits += take
            nbits -= take
            if self.nbits == 8:
                self.f.write(bytes([self.buffer]))
                self.buffer = 0
                self.nbits = 0

    def flush(self):
        if self.nbits > 0:
            self.buffer <<= (8 - self.nbits)
            self.f.write(bytes([self.buffer]))
            self.buffer = 0
            self.nbits = 0


class BitReader:
    def __init__(self, f):
        self.f = f
        self.buffer = 0
        self.nbits = 0

    def read_bit(self):
        if self.nbits == 0:
            byte = self.f.read(1)
            if not byte:
                return None
            self.buffer = byte[0]
            self.nbits = 8
        self.nbits -= 1
        return (self.buffer >> self.nbits) & 1


class Node:
    def __init__(self, freq, symbol=None, left=None, right=None):
        self.freq = freq
        self.symbol = symbol
        self.left = left
        self.right = right

#freq={byte:count}
def build_huffman_tree(freq):
    nodes=[]
    for symbol, f in freq.items():
        if f>0:
            # write leaf nodes of tree- list of nodes
            nodes.append(Node(f, symbol))

    while len(nodes)>1:

        #take two smallest freq nodes
        nodes.sort(key=lambda n: (n.freq, n.symbol if n.symbol is not None else -1))
        n1=nodes.pop(0)
        n2=nodes.pop(0)

        #merge nodes
        merged=Node(n1.freq + n2.freq, None, n1, n2)
        nodes.append(merged)
    return nodes[0]


def build_codes(node, prefix="", codes=None):
    if codes is None:
        codes={}

    if node.symbol is not None:
        codes[node.symbol] = prefix if prefix else "0"
        return codes

    build_codes(node.left, prefix + "0", codes)
    build_codes(node.right, prefix + "1", codes)
    return codes


def huffman_encode_file(in_file, out_file):
    with open(in_file, "rb") as f:
        data = f.read()

    freq=Counter(data)
    tree=build_huffman_tree(freq)
    codes=build_codes(tree)

    with open(out_file, "wb") as fout:
        writer = BitWriter(fout)

        #store og size
        fout.write(len(data).to_bytes(4, "big"))

        #for every byte, store frequency
        for i in range(256):
            fout.write(freq.get(i, 0).to_bytes(4, "big"))

        start = time.time()
        for i, b in enumerate(data):
            code = codes[b]
            writer.write_bits(int(code, 2), len(code))
            if i % 50000 == 0 and i > 0:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                print(f"Encoded {i}/{len(data)} bytes | Rate {rate:.1f} B/s", end="\r", flush=True)
        writer.flush()

    print()
    print("Huffman encoding complete.")


def huffman_decode_file(in_file, out_file):
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:
        reader = BitReader(fin)
        start = time.time()
        original_size = int.from_bytes(fin.read(4), "big")

        freq = {}
        for i in range(256):
            f = int.from_bytes(fin.read(4), "big")
            if f > 0:
                freq[i] = f

        tree = build_huffman_tree(freq)
        decoded_bytes = 0

        if tree.symbol is not None:
            fout.write(bytes([tree.symbol]) * original_size)
            print("Single-symbol file decoded")
            return

        while decoded_bytes < original_size:
            node = tree
            while node.symbol is None:
                bit = reader.read_bit()
                if bit == 0:
                    node = node.left
                else:
                    node = node.right
            fout.write(bytes([node.symbol]))
            decoded_bytes += 1

            if decoded_bytes % 50000 == 0:
                elapsed = time.time() - start
                rate = decoded_bytes / elapsed if elapsed > 0 else 0
                print(
                    f"Decoded {decoded_bytes}/{original_size} bytes | Rate {rate:.1f} B/s",
                    end="\r",
                    flush=True,
                )

    print()
    print("Huffman decoding complete.")
