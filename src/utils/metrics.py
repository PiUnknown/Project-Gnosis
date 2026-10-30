import time
import os
import gc
import logging
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

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
    return time.perf_counter()

def log_phase_end(phase_name: str, start_time: float, objects_cleaned: Optional[list] = None) -> None:
    elapsed = time.perf_counter() - start_time
    
    # 1. Print Cleanup Diagnostics
    print("\n[Cleanup]")
    if objects_cleaned:
        for obj in objects_cleaned:
            print(obj)
    force_gc = os.getenv("GNOSIS_FORCE_PHASE_GC", "0").strip().lower() in {"1", "true", "yes"}
    if force_gc:
        gc.collect()
        print("Full GC complete (GNOSIS_FORCE_PHASE_GC enabled)")
    else:
        print("Full GC deferred to Python's automatic collector")
    
    # 3. Retrieve and Log RSS Memory
    rss, vms = get_memory_usage()
    logger.info(
        "pipeline_phase_elapsed phase=%s duration_ms=%.2f rss_mb=%.0f vms_mb=%.0f",
        phase_name,
        elapsed * 1000,
        rss,
        vms,
    )
    if psutil:
        print(f"RSS: {rss:.0f} MB")
        
    print(f"\n[Memory after {phase_name}]")
    if psutil:
        print(f"RSS: {rss:.0f} MB")
        
    # 4. Standard Metrics Summary
    print(f"\n------------------------------------------------")
    print(f"[Metrics]")
    print(f"Phase: {phase_name}")
    print(f"Elapsed: {elapsed:.2f} s")
    if psutil:
        print(f"RSS: {rss:.0f} MB")
        print(f"VMS: {vms:.0f} MB")
    print(f"------------------------------------------------")
