import zipfile
import json

model_path = "ai/models/current/model_SpaceMarine_Infantry_Troop_RangedSwarm.zip"

print(f"Checking model: {model_path}\n")

with zipfile.ZipFile(model_path, 'r') as z:
    print("Files in model archive:")
    for name in z.namelist():
        print(f"  - {name}")
    
    # Try to read the data file
    try:
        with z.open('data') as f:
            data = json.load(f)
            if 'observation_space' in data:
                obs_space = data['observation_space']
                print(f"\n✅ Model's observation space: {obs_space}")
                if 'shape' in obs_space:
                    print(f"   Shape: {obs_space['shape']}")
            else:
                print(f"\n⚠️ No observation_space found in data")
                print(f"   Available keys: {list(data.keys())}")
    except json.JSONDecodeError:
        print("\n⚠️ Data file is not JSON, trying other files...")
        
        # Try policy file
        if 'policy.pth' in z.namelist():
            print("   Found policy.pth (PyTorch weights)")
        
        # Try to find any JSON files
        for name in z.namelist():
            if name.endswith('.json'):
                with z.open(name) as f:
                    data = json.load(f)
                    print(f"\n   {name} contents:")
                    print(f"   {json.dumps(data, indent=2)[:500]}")