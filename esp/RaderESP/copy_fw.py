Import("env")
import subprocess
import shutil
import os
import sys

def copy_firmware(source, target, env):
    # Get git hash
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_hash = "unknown"

    build_dir = env.subst("$BUILD_DIR")
    project_dir = env.subst("$PROJECT_DIR")
    pio_packages = os.path.expanduser("~/.platformio/packages")

    # Source binaries
    src_firmware    = os.path.join(build_dir, "firmware.bin")
    src_bootloader  = os.path.join(build_dir, "bootloader.bin")
    src_partitions  = os.path.join(build_dir, "partitions.bin")
    src_boot_app0   = os.path.join(pio_packages,
                          "framework-arduinoespressif32", "tools", "partitions", "boot_app0.bin")

    # Destination: fw/ folder
    fw_dir = os.path.join(project_dir, "fw")
    os.makedirs(fw_dir, exist_ok=True)

    # Copy firmware.bin (latest + versioned)
    shutil.copy2(src_firmware, os.path.join(fw_dir, "firmware.bin"))
    shutil.copy2(src_firmware, os.path.join(fw_dir, "firmware-%s.bin" % git_hash))
    print("[FW] Copied -> fw/firmware.bin")
    print("[FW] Copied -> fw/firmware-%s.bin" % git_hash)

    # Copy support binaries (needed for merged.bin generation)
    for src, name in [(src_bootloader, "bootloader.bin"),
                      (src_partitions, "partitions.bin"),
                      (src_boot_app0,  "boot_app0.bin")]:
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(fw_dir, name))
            print("[FW] Copied -> fw/%s" % name)
        else:
            print("[FW] WARNING: %s not found, skip" % src)

    # Generate merged.bin (single file for factory flashing)
    merged_latest    = os.path.join(fw_dir, "merged.bin")
    merged_versioned = os.path.join(fw_dir, "merged-%s.bin" % git_hash)
    esptool = os.path.join(pio_packages, "tool-esptoolpy", "esptool.py")
    if os.path.exists(esptool) and os.path.exists(src_bootloader):
        cmd = [
            sys.executable, esptool,
            "--chip", "esp32",
            "merge_bin",
            "-o", merged_latest,
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "4MB",
            "0x1000",  src_bootloader,
            "0x8000",  src_partitions,
            "0xe000",  src_boot_app0,
            "0x10000", src_firmware,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            shutil.copy2(merged_latest, merged_versioned)
            print("[FW] merged.bin -> fw/merged.bin")
            print("[FW] merged.bin -> fw/merged-%s.bin" % git_hash)
        else:
            print("[FW] WARNING: merge_bin failed:", result.stderr.strip())
    else:
        print("[FW] Skip merged.bin (esptool or bootloader not found)")

env.AddPostAction("$BUILD_DIR/firmware.bin", copy_firmware)
