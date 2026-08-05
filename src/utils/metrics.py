import time
import os
import gc
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

def get_memory_usage():
    if psutil is None:
        return 0.0, 0.0
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        rss = mem_info.rss / (1024 * 1024)  # MB
        vms = mem_info.vms / (1024 * 1024)  # MB
        return rss, vms
    except Exception:
        return 0.0, 0.0

def log_phase_start(phase_name: str) -> float:
    rss, vms = get_memory_usage()
    print(f"\n================================================")
    print(f"[Phase Start] {phase_name}")
    if psutil:
        print(f"Initial RSS: {rss:.0f} MB")
        print(f"Initial VMS: {vms:.0f} MB")
    print(f"================================================")
    return time.time()

def log_phase_end(phase_name: str, start_time: float) -> None:
    elapsed = time.time() - start_time
    rss, vms = get_memory_usage()
    print(f"\n------------------------------------------------")
    print(f"[Metrics]")
    print(f"Phase: {phase_name}")
    print(f"Elapsed: {elapsed:.2f} s")
    if psutil:
        print(f"RSS: {rss:.0f} MB")
        print(f"VMS: {vms:.0f} MB")
    print(f"------------------------------------------------")
    
    # Free heap aggressively
    gc.collect()
