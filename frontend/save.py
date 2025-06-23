# frontend/save.py
#
import os
import shutil
import datetime
import json

###########################################################################################
### VERSION
###########################################################################################
version = "v7"

# 1. Try to load config.json (if it exists)
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    ROOT = config.get("ROOT")
    DEST_ROOT = config.get("DEST_ROOT")
    files_to_copy = config.get("files_to_copy")
else:
    # 2. Otherwise, use env vars or hardcoded defaults
    ROOT = os.environ.get("PROJECT_ROOT", r"E:\Dropbox\Informatique\Holberton\40k")
    DEST_ROOT = os.environ.get("DEST_ROOT", os.path.join(ROOT, "versions", version))
    files_to_copy = [

        "export_scenario.ts",
        "generate_scenario.py",
        "package.json",
        "tsconfig.json",
        "tsconfig.base.json",
        "frontend/save.py",
        "frontend/tsconfig.json",
        "frontend/vite.config.ts",
        "frontend/package.json",

        "frontend/src/App.tsx",
        "frontend/src/routes.tsx",
        "frontend/src/main.tsx",
        "frontend/src/ai/ai.ts",

        # Pages
        "frontend/src/pages/HomePage.tsx",
        "frontend/src/pages/ReplayPage.tsx",
        "frontend/src/pages/GamePage.tsx",

        # @components
        "frontend/src/components/Board.tsx",
        "frontend/src/components/UnitSelector.tsx",

        # Replay
        "frontend/src/components/ReplayViewer.tsx",
        "frontend/src/components/LoadReplayButton.tsx",

        # @data
        "frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        "frontend/src/data/Scenario.ts",

        # @roster
        "frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts",
        "frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts",
        "frontend/src/roster/spaceMarine/Intercessor.ts",
        "frontend/src/roster/spaceMarine/AssaultIntercessor.ts",
        "frontend/src/roster/exportRewards.js",

        # dist
        "dist/data/Scenario.js",
        "dist/data/UnitFactory.js",

        # @ai
        "ai/agent.py",
        "ai/api.py",
        "ai/evaluate.py",
        "ai/gym40k.py",
        "ai/model.py",
        "ai/env_registration.py",
        "ai/state.py",
        "ai/test.py",
        "ai/train.py",
        "ai/utils.py",
    ]

logfile = os.path.join(DEST_ROOT, "backup.log")
os.makedirs(DEST_ROOT, exist_ok=True)

ok_count = 0
fail_count = 0
with open(logfile, "a", encoding="utf-8") as log:
    log.write(f"\n---- Backup run: {datetime.datetime.now()} ----\n")
    for file_rel in files_to_copy:
        src = os.path.join(ROOT, file_rel)
        dest = os.path.join(DEST_ROOT, file_rel)
        dest_dir = os.path.dirname(dest)
        if not os.path.exists(src):
            msg = f"ERROR: Source file does not exist: {src}"
            print(msg)
            log.write(msg + "\n")
            fail_count += 1
            continue
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest)
        msg = f"Copied {src} -> {dest}"
        print(msg)
        log.write(msg + "\n")
        ok_count += 1

    log.write(f"Backup finished. Success: {ok_count} | Failed: {fail_count}\n")

print(f"Backup complete. Success: {ok_count} | Failed: {fail_count}")
print(f"Log written to: {logfile}")
