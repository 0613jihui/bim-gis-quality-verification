"""out/*.city.json을 CityJSON 공식 스키마(2.0.2)로 검사하고, LoD1 솔리드가 닫힌 다면체인지 확인한다.

사용법:  python validate_cityjson.py
스키마: https://github.com/cityjson/specs (schemas/, commit 877ee49)를 schemas/ 폴더에 내려받아 사용
"""
import glob, json, os, subprocess, sys
import numpy as np
import trimesh
from jsonschema import Draft7Validator

SCHEMA_DIR = "schemas/cityjson-specs"
if not os.path.exists(SCHEMA_DIR):
    subprocess.run(["git", "clone", "-q", "https://github.com/cityjson/specs.git", SCHEMA_DIR], check=True)
    subprocess.run(["git", "-C", SCHEMA_DIR, "checkout", "-q", "877ee49"], check=True)
validator = Draft7Validator(json.load(open(f"{SCHEMA_DIR}/schemas/cityjson.min.schema.json")))

bad = 0
for path in sorted(glob.glob("out/*.city.json")):
    d = json.load(open(path))
    errors = list(validator.iter_errors(d))
    CO = d["CityObjects"]
    links = [k for k, o in CO.items() for p in o.get("parents", []) if p not in CO or k not in CO[p].get("children", [])]
    V = np.array(d["vertices"], float).reshape(-1, 3) * d["transform"]["scale"] + d["transform"]["translate"]
    solids = []
    for o in CO.values():
        for g in o.get("geometry", []):
            shells = [g["boundaries"][0]] if g["type"] == "Solid" else [s[0] for s in g["boundaries"]] if g["type"] == "MultiSolid" else []
            for sh in shells:
                tri = [[r[0], r[i], r[i + 1]] for surf in sh for r in surf[:1] for i in range(1, len(r) - 1)]
                m = trimesh.Trimesh(V, np.array(tri), process=True)
                solids.append(m.is_watertight and m.is_winding_consistent and m.volume > 0)
    ok = not errors and not links and all(solids)
    bad += not ok
    print(f"{'OK ' if ok else 'ERR'} {os.path.basename(path)}: 스키마 오류 {len(errors)}, 부모-자식 불일치 {len(links)}, "
          f"닫힌 LoD1 솔리드 {sum(solids)}/{len(solids)}")
sys.exit(1 if bad else 0)
