Import("env")
import subprocess
import shutil
import os

def copy_firmware(source, target, env):
    # Get git hash
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_hash = "unknown"

    # Source: .pio/build/esp32dev/firmware.bin
    src_bin = os.path.join(env.subst("$BUILD_DIR"), "firmware.bin")

    # Destination: fw/ folder (next to platformio.ini)
    fw_dir = os.path.join(env.subst("$PROJECT_DIR"), "fw")
    os.makedirs(fw_dir, exist_ok=True)

    # Copy as firmware.bin (always latest) and firmware-<hash>.bin (versioned)
    dst_latest = os.path.join(fw_dir, "firmware.bin")
    dst_versioned = os.path.join(fw_dir, "firmware-%s.bin" % git_hash)

    shutil.copy2(src_bin, dst_latest)
    shutil.copy2(src_bin, dst_versioned)

    print("[FW] Copied -> fw/firmware.bin")
    print("[FW] Copied -> fw/firmware-%s.bin" % git_hash)

env.AddPostAction("$BUILD_DIR/firmware.bin", copy_firmware)
