"""본문 수치 중 e1/e2/e3 기본 출력에 직접 저장되지 않는 항목을 재현하는 보조 스크립트.
실행: python extra_checks.py  (e1_analysis.py, e2_mutation.py, e3_sweep.py 실행 후)
결과: out/extra_checks.json + 화면 출력"""
import json, collections, sys, platform
import numpy as np, ifcopenshell, ifcopenshell.validate, shapely, trimesh, pyproj
import qvf

R = {}
# 0. 실험 환경 (IV-1)
R["env"] = dict(python=platform.python_version(), ifcopenshell=ifcopenshell.version, shapely=shapely.__version__,
                trimesh=trimesh.__version__, pyproj=pyproj.__version__, proj=pyproj.proj_version_str)

# 1. 공간참조 매개변수 (IV-2): 연합모델 두 계열의 IfcMapConversion, FZK-Haus 기준점
mc = {}
for f in ["bs43/Building-Architecture.ifc", "bs43/Building-Structural.ifc"]:
    g = qvf.georef_info(ifcopenshell.open(f))
    c = g["mapconv"]
    import math
    mc[f] = dict(E=round(c["E"], 2), N=round(c["N"], 2), rot_deg=round(math.degrees(math.atan2(c["b"], c["a"])), 2),
                 Scale=c["S"], crs=g["crs"])
R["mapconversion"] = mc
fzk = ifcopenshell.open("osb/AC11-FZK-Haus-IFC.ifc").by_type("IfcSite")[0]
R["fzk_ref_latlon"] = dict(RefLatitude=list(fzk.RefLatitude), RefLongitude=list(fzk.RefLongitude))

# 2. 의미 매핑 실패 요소의 내역 (IV-3)
gen = {}
for f in ["bs43/Building-Structural.ifc", "bs43/Building-Architecture.ifc", "bs43/Building-Hvac.ifc", "bs43/Building-Landscaping.ifc"]:
    m = ifcopenshell.open(f); c = collections.Counter()
    for e in qvf.physical_elements(m):
        fac = qvf.facility_of(e)
        if qvf.citygml_class(e, fac) == qvf.GENERIC:
            c[f"{e.is_a()} | 귀속시설={fac.is_a() if fac else 'IfcSite(시설 없음)'} | PredefinedType={getattr(e, 'PredefinedType', None)}"] += 1
    gen[f] = dict(c)
R["generic_breakdown"] = gen

# 3. Smiley-West 스키마 위반 유형 (IV-4)
m = ifcopenshell.open("osb/AC-20-Smiley-West-10-Bldg_fix.ifc")
lg = ifcopenshell.validate.json_logger(); ifcopenshell.validate.validate(m, lg)
R["smiley_schema_errors"] = dict(collections.Counter(f"{s['message']} :: {s.get('attribute')}" for s in lg.statements))

# 4. R10 단일 메시 판정 대비 (IV-4): 요소 메시를 하나로 합쳐 판정했을 때의 유효율
merged = {}
for f in ["osb/AC11-FZK-Haus-IFC.ifc", "osb/AC11-Institute-Var-2-IFC.ifc", "osb/AC-20-Smiley-West-10-Bldg_fix.ifc"]:
    m = ifcopenshell.open(f); meshes = qvf.triangulate(m); ok = n = 0
    for e in qvf.physical_elements(m):
        if e.id() in meshes and len(meshes[e.id()][1]) and (qvf.body_rep_type(e) in qvf.SOLID_REP or qvf.is_closed_tess(e)):
            n += 1; ok += qvf.mesh_valid(*meshes[e.id()])[0]
    merged[f] = dict(valid=ok, checked=n, rate=round(ok / n, 4))
    print("merged-mesh", f, ok, n, flush=True)
R["r10_merged_mesh"] = merged

# 5. 결함 주입 결과의 추가 집계 (V-2, V-3)
from e2_mutation import detected_rules
raw = json.load(open("out/e2_raw.json"))
clean = {r["bid"]: r["res"] for r in raw if r["mtype"] == "CLEAN"}
muts = [r for r in raw if r["mtype"] != "CLEAN" and "res" in r]
m9 = [r for r in muts if r["mtype"] == "M9_GEOM"]
R["m9_r10_values"] = [(r["bid"], r["log"].get("kind"), r["res"]["R10"]["value"]) for r in m9]
strict = 0
for r in muts:
    det = detected_rules(clean[r["bid"]], r["res"])
    cv, mv = clean[r["bid"]]["R10"]["value"], r["res"]["R10"]["value"]
    if not det and cv is not None and mv is not None and mv < 1.0:
        det = {"R10(strict)"}
    strict += bool(det)
R["detect_with_r10_zero_tolerance"] = f"{strict}/{len(muts)} = {strict / len(muts) * 100:.1f}%"
b3 = [r for r in m9 if r["bid"] == "B3" and r["res"]["R10"]["value"] is not None]
R["m3_r14_by_base"] = {b: sorted(set(round(r["res"]["R14"]["value"], 3) for r in muts if r["mtype"] == "M3_GEO_ROT" and r["bid"] == b)) for b in ["B1", "B2", "B3", "B4"]}
R["b3_worst_m9"] = dict(rate=min(r["res"]["R10"]["value"] for r in b3), invalid_of_90=round(90 * (1 - min(r["res"]["R10"]["value"] for r in b3))))
tau = {}
for mt in ["M2_GEO_SHIFT", "M3_GEO_ROT"]:
    v = [r["res"]["R14"]["value"] for r in muts if r["mtype"] == mt]
    tau[mt] = {t: f"{sum(x > t for x in v)}/{len(v)}" for t in [0.05, 0.1, 0.2, 0.3, 0.5, 1.0]}
R["tau_sensitivity"] = tau

# 6. 회전 민감도의 임계각 (V-4, 그림 2): tau / (1도에서의 편차)
sw = json.load(open("out/e3_sweep.json"))
R["critical_angle_deg_tau0.2"] = {b: round(0.2 / next(x["dev"] for x in sw if x["bid"] == b and x["kind"] == "rot" and x["v"] == 1.0 and x["sign"] == 1), 2)
                                  for b in ["B1", "B2", "B3", "B4"]}
R["shift_max_abs_diff_m"] = max(abs(x["dev"] - x["v"]) for x in sw if x["kind"] == "shift")

json.dump(R, open("out/extra_checks.json", "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
