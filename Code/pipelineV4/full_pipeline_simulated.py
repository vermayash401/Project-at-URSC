from pathlib import Path
from telemetery_simulator import mixed_telemetry
from full_pipeline_import import run_chain


def main():
    days = 1
    max_changes = [1, 2, 4, 8, 16, 32, 64]

    root = Path(__file__).resolve().parent.parent
    txt_file = root / "original_telemetry_v4_simulated.txt"
    out_dir = root / "pipelineV4_outputs_simulated"

    print("Generating mixed telemetry...")
    mixed_telemetry(days, max_changes, str(txt_file))

    print("Running import pipeline on simulated telemetry...")
    run_chain(str(txt_file), str(out_dir))


if __name__ == "__main__":
    main()
