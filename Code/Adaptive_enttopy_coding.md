## Requirements

- Windows 64-bit
- Visual Studio Build Tools 2022 (Desktop development with C++)
- CMake
- libaec

## Build libaec

Open "x64 Native Tools Command Prompt for VS 2022"

cd libaec-1.1.5
mkdir build
cd build
cmake -G "NMake Makefiles" ..
nmake

Executable will be located in:
build/src/graec.exe

## Compress

graec.exe input_delta.bin output.aec

## Decompress

graec.exe -d output.aec recovered.bin
