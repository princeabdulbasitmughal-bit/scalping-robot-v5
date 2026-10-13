#!/usr/bin/env python3
"""
Scalping Robot V5 - Universal MetaTrader Auto-Installer and Setup Assistant
Scans for installed MT4/MT5 instances and installs the EA and Presets with 1-click.
"""

import os
import sys
import shutil
import glob
import string
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
EXPERTS_SRC = CURRENT_DIR / "Scalping Robot V5" / "MQL4" / "Experts"
PRESETS_SRC = CURRENT_DIR / "Presets"

def find_mt4_directories():
    found = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        metaquotes_dir = os.path.join(appdata, "MetaQuotes", "Terminal")
        if os.path.exists(metaquotes_dir):
            for entry in os.listdir(metaquotes_dir):
                full_path = os.path.join(metaquotes_dir, entry)
                if os.path.isdir(full_path):
                    mql4_dir = os.path.join(full_path, "MQL4")
                    if os.path.exists(mql4_dir):
                        found.append(full_path)
    # Use environment variables for Program Files paths (locale-safe)
    prog_files = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    ]
    # Dynamically probe all available drive letters — avoids hardcoding E:\MetaTrader
    for drive in string.ascii_uppercase:
        candidate = f"{drive}:\\MetaTrader"
        prog_files.append(candidate)
    for base in prog_files:
        if base and os.path.exists(base):
            # Escape base path to handle directory names containing brackets ([])
            safe_base = glob.escape(base)
            for candidate in glob.glob(os.path.join(safe_base, "*MetaTrader*", "MQL4")):
                parent = os.path.dirname(candidate)
                if parent not in found:
                    found.append(parent)
    return found

def install_to_target(target_dir):
    mql4_experts = os.path.join(target_dir, "MQL4", "Experts")
    mql4_presets = os.path.join(target_dir, "MQL4", "Presets")
    try:
        os.makedirs(mql4_experts, exist_ok=True)
        os.makedirs(mql4_presets, exist_ok=True)
    except PermissionError as e:
        print(f"  [ERROR] Cannot create directories in {target_dir}: {e}")
        print("  Try running this script as Administrator.")
        return []

    installed_files = []
    errors = []

    if os.path.exists(EXPERTS_SRC):
        try:
            expert_files = os.listdir(EXPERTS_SRC)
        except PermissionError as e:
            errors.append(f"  [ERROR] Cannot list EXPERTS_SRC: {e}")
            expert_files = []
        for f in expert_files:
            # Case-insensitive extension check
            if f.lower().endswith(".ex4") or f.lower().endswith(".mq4"):
                src = os.path.join(EXPERTS_SRC, f)
                dst = os.path.join(mql4_experts, f)
                try:
                    shutil.copy2(src, dst)
                    installed_files.append(f"EA: {f}")
                except PermissionError as e:
                    errors.append(f"  [ERROR] Cannot copy {f} -> Experts (permission denied): {e}")
                except Exception as e:
                    errors.append(f"  [ERROR] Failed to copy {f} -> Experts: {e}")

    if os.path.exists(PRESETS_SRC):
        try:
            preset_files = os.listdir(PRESETS_SRC)
        except PermissionError as e:
            errors.append(f"  [ERROR] Cannot list PRESETS_SRC: {e}")
            preset_files = []
        for f in preset_files:
            if f.lower().endswith(".set"):
                src = os.path.join(PRESETS_SRC, f)
                dst = os.path.join(mql4_presets, f)
                try:
                    shutil.copy2(src, dst)
                    installed_files.append(f"Preset: {f}")
                except PermissionError as e:
                    errors.append(f"  [ERROR] Cannot copy {f} -> Presets (permission denied): {e}")
                except Exception as e:
                    errors.append(f"  [ERROR] Failed to copy {f} -> Presets: {e}")

    for err in errors:
        print(err)

    return installed_files


def main():
    print("="*70)
    print("  SCALPING ROBOT V5 UNIVERSAL METATRADER INSTALLER")
    print("="*70)

    if len(sys.argv) > 1:
        custom_path = sys.argv[1].strip('"')
        if os.path.exists(custom_path):
            print(f"Installing to specified directory: {custom_path}")
            installed = install_to_target(custom_path)
            if installed:
                print(f"Successfully installed {len(installed)} files!")
                for item in installed:
                    print(f"  [OK] {item}")
            else:
                print("[WARNING] No files were installed. Check errors above.")
            return
        else:
            print(f"Specified path not found: {custom_path}")

    targets = find_mt4_directories()
    if not targets:
        print("[INFO] No active MetaTrader 4 data folders found automatically in AppData.")
        print("If MetaTrader 4 is installed elsewhere or running in portable mode,")
        print("run this script with your MT4 data directory as an argument:")
        print(r'  python auto_install_to_mt4.py "C:\Path\To\Your\MT4\DataFolder"')
        print("\nTo find your MT4 Data Folder:")
        print("  1. Open MetaTrader 4")
        print("  2. Click File -> Open Data Folder")
        print("  3. Copy the path and pass it to this installer.")
        return

    print(f"Found {len(targets)} MetaTrader installation(s):")
    for idx, t in enumerate(targets):
        print(f"  [{idx+1}] {t}")
        installed = install_to_target(t)
        if installed:
            for item in installed:
                print(f"      [OK] Installed {item}")
        else:
            print(f"  [WARNING] No files installed to {t} — check errors above.")

    print("\nInstallation Complete! Next Steps in MT4:")
    print("1. Restart or refresh MetaTrader 4 Navigator window (Right click -> Refresh).")
    print("2. In Tools -> Options -> Expert Advisors, check:")
    print("   - Allow automated trading")
    print("   - Allow DLL imports")
    print('3. Drag "Scalping Robot 5.0 EA" onto a 1-Minute (M1) or 5-Minute (M5) XAUUSD or EURUSD chart.')
    print('4. Click "Load" and choose Safe_Scalper_XAUUSD_M1.set or Conservative_EURUSD_M5.set.')
    print("="*70)

if __name__ == "__main__":
    main()
