import random
import math

output_file='telemetry_dataset.hex'

header=[0xFC, 0xCA, 0x1D, 0xF9]
footer=[0xA5, 0xA5]

total_frames=60*60*24*30 #sec(frame) in one month-generating one month data
frames_per_mode=total_frames//4
payload_size= 5 #bytes

stable_payload = [random.randint(0, 255) for _ in range(payload_size)]

drift_reference = [random.randint(20, 200) for _ in range(payload_size)]


def int_to_hex_string (value, width):
    return format(value, f'0{width}X')

def frameid(num):
    frame_id_bytes = num.to_bytes(4, byteorder='big')
    return list(frame_id_bytes)

def payload_stable():
    return stable_payload

def payload_slow_drift():
    payload = []
    for ref in drift_reference:
        delta = random.randint(-9, 9)
        value = min(255, max(0, ref + delta))
        payload.append(value)
    return payload

def payload_correlated(t):
    payload = []
    for i in range(payload_size):
        value = int(128+ 40 * math.sin(0.05 * t + i)+ (t % 20)) & 0xFF
        payload.append(value)
    return payload
    
def payload_noisy():
    return [random.randint(0, 255) for _ in range(payload_size)]


with open(output_file, 'w') as file:
    for i in range (total_frames): 

        if i < frames_per_mode:
            payload = payload_stable()
        elif i < 2 * frames_per_mode:
            payload = payload_slow_drift()
        elif i < 3 * frames_per_mode:
            payload = payload_correlated(i)
        else:
            payload = payload_noisy()
        
        frame=[]
        frame.extend(header)
        frame.extend(frameid(i))
        frame.extend(payload)
        frame.extend(footer)

        hex_frame=' '.join(int_to_hex_string (i, 2) for i in frame)

        file.write(hex_frame + '\n')
print('done')
