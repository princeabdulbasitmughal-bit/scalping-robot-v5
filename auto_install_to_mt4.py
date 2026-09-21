#!/usr/bin/env python3
"""
Scalping Robot V5 - Universal MetaTrader Auto-Installer and Setup Assistant
Scans for installed MT4/MT5 instances and installs the EA and Presets with 1-click.
"""

import os
import sys
import shutil
import glob

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
EXPERTS_SRC = os.path.join(CURRENT_DIR, "Scalping Robot V5", "MQL4", "Experts")
PRESETS_SRC = os.path.join(CURRENT_DIR, "Presets")

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
    prog_files = [r"C:\Program Files", r"C:\Program Files (x86)", r"E:\MetaTrader"]
    for base in prog_files:
        if os.path.exists(base):
            for candidate in glob.glob(os.path.join(base, "*MetaTrader*", "MQL4")):
                parent = os.path.dirname(candidate)
                if parent not in found:
                    found.append(parent)
    return found

def install_to_target(target_dir):
    mql4_experts = os.path.join(target_dir, "MQL4", "Experts")
    mql4_presets = os.path.join(target_dir, "MQL4", "Presets")
    os.makedirs(mql4_experts, exist_ok=True)
    os.makedirs(mql4_presets, exist_ok=True)
    
    installed_files = []
    if os.path.exists(EXPERTS_SRC):
        for f in os.listdir(EXPERTS_SRC):
            if f.endswith(".ex4") or f.endswith(".mq4"):
                src = os.path.join(EXPERTS_SRC, f)
                dst = os.path.join(mql4_experts, f)
                shutil.copy2(src, dst)
                installed_files.append(f"EA: {f}")
                
    if os.path.exists(PRESETS_SRC):
        for f in os.listdir(PRESETS_SRC):
            if f.endswith(".set"):
                src = os.path.join(PRESETS_SRC, f)
                dst = os.path.join(mql4_presets, f)
                shutil.copy2(src, dst)
                installed_files.append(f"Preset: {f}")
                
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
            print(f"Successfully installed {len(installed)} files!")
            for item in installed:
                print(f"  [OK] {item}")
            return
        else:
            print(f"Specified path not found: {custom_path}")
            
    targets = find_mt4_directories()
    if not targets:
        print("[INFO] No active MetaTrader 4 data folders found automatically in AppData.")
        print("If MetaTrader 4 is installed elsewhere or running in portable mode,")
        print("run this script with your MT4 data directory as an argument:")
        print('  python auto_install_to_mt4.py "C:\Path\To\Your\MT4\DataFolder"')
        print("\nTo find your MT4 Data Folder:")
        print("  1. Open MetaTrader 4")
        print("  2. Click File -> Open Data Folder")
        print("  3. Copy the path and pass it to this installer.")
        return
        
    print(f"Found {len(targets)} MetaTrader installation(s):")
    for idx, t in enumerate(targets):
        print(f"  [{idx+1}] {t}")
        installed = install_to_target(t)
        for item in installed:
            print(f"      [OK] Installed {item}")
            
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
