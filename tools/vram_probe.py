# -*- coding: utf-8 -*-
"""Video card probe: separates memory failure from power failure.

Usage:
    python vram_probe.py mem
    python vram_probe.py pwr
"""
import os, sys, time, subprocess

FOLDER = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(FOLDER, "vram_probe_log.txt")


def log_line(text):
    timestamp = time.strftime("%H:%M:%S")
    line = "%s  %s" % (timestamp, text)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def sensors():
    try:
        raw = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=power.draw,temperature.gpu,clocks.sm,clocks.mem",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout.strip()
        parts = [p.strip() for p in raw.split(",")]
        return "%sW %sC core %sMHz mem %sMHz" % (parts[0], parts[1], parts[2], parts[3])
    except Exception:
        return "sensors unavailable"


def test_memory(torch):
    BLOCK_SIZE = 256 * 1024 * 1024
    ELEMENTS = BLOCK_SIZE // 4
    blocks = []
    pattern = None
    log_line("MODE MEMORY: 256MB blocks, write pattern and verify")
    log_line("start: " + sensors())

    step = 0
    while True:
        step += 1
        allocated_gb = step * 256 / 1024.0
        try:
            if pattern is None:
                pattern = torch.arange(ELEMENTS, device="cuda", dtype=torch.int32)
                pattern = (pattern * 2654435761) ^ 0x5bf03635
            block = pattern.clone()
            blocks.append(block)
        except RuntimeError as e:
            log_line("memory ran out at %.2f GB: %s" % (allocated_gb, str(e)[:120]))
            break

        errors_new = int((block != pattern).sum().item())
        old_block = blocks[step // 2] if step > 3 else block
        errors_old = int((old_block != pattern).sum().item())
        torch.cuda.synchronize()

        log_line("allocated %5.2f GB | errors new %d | errors old %d | %s"
                 % (allocated_gb, errors_new, errors_old, sensors()))

        if errors_new or errors_old:
            log_line("!!! FAULTY MEMORY DETECTED at %.2f GB" % allocated_gb)
            break
        if allocated_gb >= 14.0:
            log_line("reached 14 GB with zero errors - memory is clean")
            break
        time.sleep(0.15)

    log_line("MODE MEMORY completed normally")


def test_power(torch):
    log_line("MODE POWER: 8192x8192 matrices, < 1GB memory")
    log_line("start: " + sensors())
    a = torch.randn(8192, 8192, device="cuda", dtype=torch.float16)
    b = torch.randn(8192, 8192, device="cuda", dtype=torch.float16)
    start = time.time()
    iteration = 0
    peak_w = 0.0
    while time.time() - start < 600:
        iteration += 1
        for _ in range(20):
            c = a @ b
        torch.cuda.synchronize()
        sensors_str = sensors()
        try:
            watts = float(sensors_str.split("W")[0])
            peak_w = max(peak_w, watts)
        except Exception:
            pass
        log_line("iter %3d | elapsed %4.0f s | %s | peak %.0f W"
                 % (iteration, time.time() - start, sensors_str, peak_w))
        time.sleep(1.0)
    log_line("MODE POWER sustained 10 minutes, peak %.0f W" % peak_w)


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if mode not in ("mem", "memory", "pwr", "power"):
        print("usage:  python vram_probe.py mem   |   python vram_probe.py pwr")
        return 2
    log_line("=" * 70)
    log_line("probe started, mode: " + mode)
    try:
        import torch
    except Exception as e:
        log_line("torch not found: %s" % e)
        return 1
    if not torch.cuda.is_available():
        log_line("CUDA unavailable - card not visible from torch")
        return 1
    log_line("card: %s, total memory %.1f GB"
             % (torch.cuda.get_device_name(0),
                torch.cuda.get_device_properties(0).total_memory / 1024 ** 3))
    if mode in ("mem", "memory"):
        test_memory(torch)
    else:
        test_power(torch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
