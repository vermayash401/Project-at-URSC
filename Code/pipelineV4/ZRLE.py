import os

#tags(headers for 2 packets)
tag_zero=0x00
tag_literal=0x01

#maximum run of zeros stored in one packet.
max_zeros=0xFFFFFFFF #max of 4 bytes
max_literals=0xFFFF #max of 2 bytes


def zero_rle_encode(in_file, out_file, chunk_size=65536):#65536=max 2 byte value
    original_size = os.path.getsize(in_file)
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        #output file structure (all binary):

        #header-(8 bytes) original size

        #stream of packets until EOF:
        #packet 0-(1 byte) tag and (4 bytes) zero count
        #Packet literal-(1 byte) tag, (2 bytes) literal length, (N bytes) literal payload

        #write header
        #8=length, byteorder= little endian = LSB(rightmost byte) of value stored first, unsigned=positive only
        fout.write(original_size.to_bytes(8, byteorder="little", signed=False))

        zero_run=0

        #mutable array of bytes
        literal_buf=bytearray()

        #write all literals stroed in buffer with header, length, and literal as a packet
        def flush_literal():
            nonlocal literal_buf
            while literal_buf:
                take=min(len(literal_buf), max_literals)
                fout.write(bytes([tag_literal]))
                fout.write(take.to_bytes(2, byteorder="little", signed=False))
                fout.write(literal_buf[:take])
                del literal_buf[:take]

        #write count of zeros stored in buffer with header, length as packet
        def flush_zero_run():
            nonlocal zero_run
            while zero_run > 0:
                take=min(zero_run, max_zeros)
                fout.write(bytes([tag_zero]))
                fout.write(take.to_bytes(4, byteorder="little", signed=False))
                zero_run-=take

        #main logic
        while True:
            #read these many bytes
            chunk=fin.read(chunk_size)
            if not chunk:
                break
            for b in chunk:
                #when zero encountered
                if b==0:
                    if literal_buf:
                        flush_literal()
                    zero_run+=1
                    if zero_run==max_zeros:
                        flush_zero_run()
                else:
                    if zero_run:
                        flush_zero_run()
                    literal_buf.append(b)
                    if len(literal_buf)==max_literals:
                        flush_literal()
        #EOF
        if zero_run:
            flush_zero_run()
        if literal_buf:
            flush_literal()


def zero_rle_decode(in_file, out_file, zero_chunk_size=65536):
    with open(in_file, "rb") as fin, open(out_file, "wb") as fout:

        original_size_raw=fin.read(8)

        if len(original_size_raw)!=8:
            raise ValueError("Invalid ZRLE file: truncated original-size field")
        
        expected_size=int.from_bytes(original_size_raw, byteorder="little", signed=False)

        written=0

        def write_zeros(count):
            nonlocal written
            block=b"\x00" * min(zero_chunk_size, 65536)
            remaining=count
            while remaining>0:
                take=min(remaining, len(block))
                fout.write(block[:take])
                written+=take
                remaining-=take

        while True:
            tag_raw=fin.read(1)
            if not tag_raw:
                break

            tag=tag_raw[0]
            if tag==tag_zero:
                count_raw=fin.read(4)
                if len(count_raw)!=4:
                    raise ValueError("Truncated zero-run packet")
                count=int.from_bytes(count_raw, byteorder="little", signed=False)
                if count==0:
                    raise ValueError("Invalid zero-run packet with count 0")
                if written+count>expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                write_zeros(count)

            elif tag==tag_literal:
                length_raw = fin.read(2)
                if len(length_raw)!= 2:
                    raise ValueError("Truncated literal packet length")
                length=int.from_bytes(length_raw, byteorder="little", signed=False)
                if length==0:
                    raise ValueError("Invalid literal packet with length 0")
                payload=fin.read(length)
                if len(payload)!=length:
                    raise ValueError("Truncated literal packet payload")
                if written+length>expected_size:
                    raise ValueError("Decoded output would exceed header original size")
                fout.write(payload)
                written+=length
            else:
                raise ValueError(f"Invalid packet tag in ZRLE stream: 0x{tag:02X}")

        if written!=expected_size:
            raise ValueError(f"Decoded size mismatch: expected {expected_size} bytes, got {written}")
