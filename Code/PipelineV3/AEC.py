from __future__ import annotations
import os
import subprocess
from pathlib import Path


# =========================
#MODE = "compress"  # "build", "compress", "decompress"

LIBAEC_DIR = Path(r"D:/coding programs or libraries/libaec-1.1.5/libaec-1.1.5")
#INPUT_FILE = Path(r"D:/URSC/Code/spacecraft_frames6_delta.bin")   # for compress
#OUTPUT_FILE = Path(r"D:/URSC/Code/spacecraft_frames6_delta_compressed.aec")       # for compress

# For decompress mode:
#DECOMP_INPUT_FILE = Path(r"D:/URSC/Code/spacecraft_frames6_delta_compressed.aec")
#DECOMP_OUTPUT_FILE = Path(r"D:/URSC/Code/spacecraft_frames6_delta_decompmessed.bin")
# =========================


def run(cmd, cwd=None):
    #print(">", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def find_vs_vcvars64() -> Path:
    vswhere = Path(r"C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
    if not vswhere.exists():
        raise FileNotFoundError("vswhere.exe not found. Install Visual Studio Build Tools 2022.")

    result = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    install_path = result.stdout.strip()
    if not install_path:
        raise RuntimeError("Could not find Visual Studio C++ tools installation.")

    vcvars64 = Path(install_path) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars64.exists():
        raise FileNotFoundError(f"vcvars64.bat not found at: {vcvars64}")
    return vcvars64


def build_libaec(libaec_dir: Path) -> Path:
    libaec_dir = libaec_dir.resolve()
    build_dir = libaec_dir / "build"
    build_dir.mkdir(exist_ok=True)

    vcvars64 = find_vs_vcvars64()
    cmd = f'call "{vcvars64}" && cmake -G "NMake Makefiles" .. && nmake'
    run(["cmd.exe", "/d", "/s", "/c", cmd], cwd=build_dir)

    graec = build_dir / "src" / "graec.exe"
    if not graec.exists():
        raise FileNotFoundError(f"graec.exe not found: {graec}")
    return graec


def get_graec(libaec_dir: Path) -> Path:
    graec = libaec_dir.resolve() / "build" / "src" / "graec.exe"
    if graec.exists():
        return graec
    print("graec.exe not found, building libaec...")
    return build_libaec(libaec_dir)


def AEC(MODE, INPUT_FILE, OUTPUT_FILE, DECOMP_INPUT_FILE, DECOMP_OUTPUT_FILE):
    graec = get_graec(LIBAEC_DIR)

    if MODE == "build":
        print(f"Build complete: {graec}")
        return

    if MODE == "compress":
        run([str(graec), str(Path(INPUT_FILE).resolve()), str(Path(OUTPUT_FILE).resolve())])
        print(f"COMPRESSED: {Path(OUTPUT_FILE)}")
        print("COMPRESSEION RATIO (binary to transmiting file) = ", os.path.getsize(INPUT_FILE)/os.path.getsize(OUTPUT_FILE), " : 1")
        print("Data size reduced by ",  (1-(os.path.getsize(OUTPUT_FILE)/os.path.getsize(INPUT_FILE)))*100,"%")
        return

    if MODE == "decompress":
        run([str(graec), "-d", str(Path(DECOMP_INPUT_FILE).resolve()), str(Path(DECOMP_OUTPUT_FILE).resolve())])
        print("------------------------------------------------------------------------")
        print(f"DECOMPRESSED: {Path(DECOMP_OUTPUT_FILE)}")
        print("------------------------------------------------------------------------")
        return
    
   
    raise ValueError("MODE must be one of: build, compress, decompress")

'''
if __name__ == "__main__":
    main()
'''