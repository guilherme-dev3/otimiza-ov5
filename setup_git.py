import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

MINGIT_URL = "https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.2/MinGit-2.56.0.2-64-bit.zip"
TARGET_DIR = Path.home() / ".mingit"
GIT_EXE = TARGET_DIR / "cmd" / "git.exe"

def ensure_git():
    if GIT_EXE.exists():
        print(f"Git already installed at: {GIT_EXE}")
        return GIT_EXE

    print(f"Downloading MinGit from {MINGIT_URL}...")
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(MINGIT_URL, headers=headers)
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
    
    print(f"Extracting {len(content)} bytes to {TARGET_DIR}...")
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        zf.extractall(TARGET_DIR)
    
    print(f"Git successfully extracted to {GIT_EXE}")
    return GIT_EXE

def run_git(cmd):
    git_bin = str(GIT_EXE)
    full_cmd = [git_bin] + cmd
    print(f">> git {' '.join(cmd)}")
    res = subprocess.run(full_cmd, capture_output=True, text=True, errors="replace")
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print("STDERR:", res.stderr.strip())
    return res.returncode

def main():
    git = ensure_git()
    if not git.exists():
        print("Failed to locate git.exe")
        sys.exit(1)

    # Add to user PATH if not present
    cmd_dir = str(TARGET_DIR / "cmd")
    user_path = os.environ.get("PATH", "")
    if cmd_dir.lower() not in user_path.lower():
        try:
            # Set persistent user PATH in Windows Registry
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                cur_val, _ = winreg.QueryValueEx(key, "Path")
                if cmd_dir.lower() not in cur_val.lower():
                    new_val = cur_val.rstrip(";") + ";" + cmd_dir
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_val)
                    print("Added MinGit to Windows user PATH")
        except Exception as e:
            print("Note on registry PATH:", e)

    # Initialize repository
    run_git(["init"])
    run_git(["config", "user.name", "guilherme-dev3"])
    run_git(["config", "user.email", "guilherme-dev3@users.noreply.github.com"])
    run_git(["add", "."])
    run_git(["status"])
    run_git(["commit", "-m", "feat: Otimizador do Windows e Navegadores v5.0"])
    run_git(["branch", "-M", "main"])
    run_git(["remote", "remove", "origin"])
    run_git(["remote", "add", "origin", "https://github.com/guilherme-dev3/otimiza-ov5.git"])
    run_git(["remote", "-v"])

if __name__ == "__main__":
    main()
