"""
gpu_guard.py — GPU VRAM Health Check for GenerativeAI
======================================================
Checks available GPU VRAM before invoking local diffusion models.

Returns a RESOURCE_CONSTRAINED result (not a silent hang or crash) if
headroom is insufficient — same fail-fast principle as Kavach's
tool-missing fallbacks.

This is a soft check — the actual local model CLI is what runs the inference.
We query memory state beforehand and surface a clear error if it's not viable.

Note: GPU memory querying is best-effort. If nvidia-smi / Metal tools are
unavailable we log a WARNING and proceed (don't block on missing tooling).
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("Engineer.GenerativeAI.GPUGuard")

# Minimum free VRAM in MB to proceed with a diffusion model load
MIN_FREE_VRAM_MB = int(os.getenv("ENGINEER_MIN_FREE_VRAM_MB", "4096"))  # 4 GB default


@dataclass
class VRAMStatus:
    available: bool          # True = enough VRAM, proceed; False = constrained
    free_mb: Optional[int]   # Free VRAM in MB, None if undetectable
    total_mb: Optional[int]  # Total VRAM in MB, None if undetectable
    reason: str              # Human-readable status message


def check_gpu_vram(min_free_mb: int = MIN_FREE_VRAM_MB) -> VRAMStatus:
    """
    Query GPU VRAM availability.

    Tries nvidia-smi first (CUDA), falls back to a psutil virtual_memory
    check (rough proxy for unified memory / Metal). If neither works, returns
    available=True with a warning — don't block on missing tooling.
    """
    # ── Attempt 1: nvidia-smi (CUDA GPUs) ─────────────────────────────────
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            if lines:
                parts = lines[0].split(",")
                free_mb  = int(parts[0].strip())
                total_mb = int(parts[1].strip())
                available = free_mb >= min_free_mb
                reason = (
                    f"CUDA VRAM: {free_mb} MB free / {total_mb} MB total"
                    + ("" if available else f" — below minimum {min_free_mb} MB")
                )
                logger.info(f"[GPUGuard] {reason}")
                return VRAMStatus(available=available, free_mb=free_mb, total_mb=total_mb, reason=reason)
    except FileNotFoundError:
        logger.debug("[GPUGuard] nvidia-smi not found — trying fallback.")
    except Exception as exc:
        logger.warning(f"[GPUGuard] nvidia-smi error: {exc}")

    # ── Attempt 2: psutil system RAM as proxy (Apple Silicon / CPU fallback) ──
    try:
        import psutil
        vm = psutil.virtual_memory()
        free_mb  = vm.available // (1024 * 1024)
        total_mb = vm.total     // (1024 * 1024)
        available = free_mb >= min_free_mb
        reason = (
            f"System RAM (proxy): {free_mb} MB free / {total_mb} MB total"
            + ("" if available else f" — below minimum {min_free_mb} MB")
        )
        logger.info(f"[GPUGuard] {reason}")
        return VRAMStatus(available=available, free_mb=free_mb, total_mb=total_mb, reason=reason)
    except ImportError:
        logger.warning("[GPUGuard] psutil not available — cannot check memory.")
    except Exception as exc:
        logger.warning(f"[GPUGuard] psutil error: {exc}")

    # ── Fallback: undetectable — proceed with warning ──────────────────────
    reason = "VRAM/RAM check unavailable — proceeding with caution."
    logger.warning(f"[GPUGuard] {reason}")
    return VRAMStatus(available=True, free_mb=None, total_mb=None, reason=reason)
