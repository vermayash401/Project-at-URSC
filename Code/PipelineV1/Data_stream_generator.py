import math
import random

master_frame_size=32
header=[0xFC, 0xCA, 0x1D, 0xF9]
footer=[0xA5, 0xA5]

satsourceA=288 #example-temp
satsourceB=12.0 #example-voltage

def int_to_hex_string (value, width):
    return format(value, f'0{width}X')

output_file='telemetry_stream.hex'

master_frame=[]

for frame_id in range(master_frame_size):

    satsourceA=satsourceA+random.choice([-1,0,1]) #temp will vary randomly by 1 unit
    satsourceA= max(273, min(303, satsourceA)) # I have set the limits

    satsourceB=12-0.03*(satsourceA-288)+random.uniform(-0.05,0.05) #random relation

    satsourceA_telemetry=satsourceA-273 #as 0-30 int will be converted to 1 byte hex
    satsourceB_telemetry=int(satsourceB*100) #as 4 digit into will be converted to 2 bytes hex

    frame=[]
    frame.extend(header)
    frame.append(frame_id & 0xFF) #0xFF is 11111111 and is used for enforcing 1 byte hex. if frame_id >255 the it will be divided into MSB and Lsb like source B and put as 2 bytes.
    frame.append(satsourceA_telemetry & 0xFF) #same logic
    frame.append((satsourceB_telemetry>>8)& 0xFF) #right shift(MSB)-first byte
    frame.append(satsourceB_telemetry& 0xFF) #LSB
    frame.extend(footer)

    hex_frame=' '.join(int_to_hex_string (i, 2) for i in frame)

    master_frame.append(hex_frame)

with open(output_file,'w') as file:
    for i in master_frame:
        file.write(i+'\n')

print('done')