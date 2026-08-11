Import("env")
import subprocess

try:
    git_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    git_hash = "unknown"

env.Append(CPPDEFINES=[("GIT_HASH", '\\"%s\\"' % git_hash)])
print("[GIT] GIT_HASH =", git_hash)
