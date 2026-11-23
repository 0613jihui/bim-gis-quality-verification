"""검증 뷰어(docs/viewer)용 데이터 추출.

e1_analysis.py, e2_mutation.py, e3_sweep.py를 실행한 뒤 실행한다.
  python viewer_export.py  →  docs/viewer/data/{summary,B1,B2,B3,B4}.json

- summary.json : 7개 모델 규칙별 판정(E1), 결함×규칙 탐지 행렬과 변이 모델 목록(E2), 민감도(E3), 대표 4종의 평면 윤곽
- B?.json      : 대표 모델의 부재별 형상(지도좌표, cm 정수, base64)과 규칙별 표시 정보
"""
import base64
import json
import os
import collections

import numpy as np
import ifcopenshell
import ifcopenshell.util.element as ue

import qvf
from e2_mutation import BASES, EXPECTED, detected_rules

OUT = "docs/viewer/data"
os.makedirs(OUT, exist_ok=True)
E1 = json.load(open("out/e1_results.json"))
E2 = json.load(open("out/e2_raw.json"))
E2S = json.load(open("out/e2_summary.json"))
E3 = json.load(open("out/e3_sweep.json"))


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def rings(geom, o):
    if geom is None or geom.is_empty:
        return []
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    return [[[round(x - o[0], 3), round(y - o[1], 3)] for x, y in p.exterior.coords] for p in polys if p.area > 1e-6]


plans = {}
for bid, f in BASES.items():
    m = ifcopenshell.open(f)
    g = qvf.georef_info(m)
    meshes = qvf.triangulate(m)
    phys = qvf.physical_elements(m)
    conv = qvf.convert(m, g, meshes, phys)
    T = conv["T"]
    feats = {r["guid"]: r for r in conv["features"]}

    # 지도좌표 원점: 전체 형상의 최소점(cm 정수 표현용)
    allv = np.vstack([T(meshes[e.id()][0]) for e in phys if e.id() in meshes and len(meshes[e.id()][1])])
    o = allv.min(0)
    span = allv.max(0) - o
    assert (span * 100 < 32000).all(), span

    guids = collections.Counter(e.GlobalId for e in phys)
    els, V, I = [], [], []
    nv = ni = 0
    for e in phys:
        rec = feats.get(e.GlobalId, {})
        fac = qvf.facility_of(e)
        env = qvf.is_a_any(e, qvf.ENVELOPE) and (fac is None or fac.is_a("IfcBuilding"))
        isext = None
        if env:
            ps = ue.get_psets(e)
            isext = any("IsExternal" in d for k, d in ps.items() if k and k.startswith("Pset_") and k.endswith("Common"))
        unc = ue.get_container(e) is None and ue.get_aggregate(e) is None and ue.get_nest(e) is None
        d = dict(g=e.GlobalId, ifc=e.is_a(), name=e.Name or "", cls=rec.get("cls", qvf.citygml_class(e, fac)),
                 proxy=e.is_a("IfcBuildingElementProxy"), env=env, isext=isext, unc=unc, dup=guids[e.GlobalId] > 1,
                 solid=rec.get("solid_check"))
        if e.id() in meshes and len(meshes[e.id()][1]):
            v, fc = meshes[e.id()]
            assert len(v) < 65536
            q = np.round((T(v) - o) * 100).astype(np.int16)
            V.append(q); I.append(fc.astype(np.uint16))
            d.update(v=[nv, len(v)], t=[ni, len(fc)])
            nv += len(v); ni += len(fc)
            d["tri"] = True
        else:
            d["tri"] = False
        els.append(d)

    fac = [fa for fa in conv["facilities"] if fa["lod"] == 1]
    lod1 = [dict(name=fa["name"], rings=rings(fa["footprint"], o), z=[round(fa["zmin"] - o[2], 3), round(fa["zmax"] - o[2], 3)],
                 valid=fa.get("lod1_valid")) for fa in fac]
    pivot = T(np.zeros((1, 3)))[0] if g["mapconv"] else T(np.array([[c * g["unit"] for c in g["site_origin"]]]))[0]
    r1 = E1[f]
    model = dict(id=bid, file=f.split("/")[-1], schema=m.schema, crs=conv["crs"], mode=conv["mode"], level=g["level"],
                 origin=[round(x, 3) for x in o.tolist()], pivot=[round(pivot[0] - o[0], 3), round(pivot[1] - o[1], 3)],
                 facility=r1["facilities"], rules=r1["results"], lod1=lod1, elements=els,
                 verts=b64(np.vstack(V)), idx=b64(np.vstack(I)), nv=nv, ni=ni)
    json.dump(model, open(f"{OUT}/{bid}.json", "w"), ensure_ascii=False, separators=(",", ":"), default=str)
    plans[bid] = dict(lod1=lod1, pivot=model["pivot"], crs=conv["crs"])
    print(bid, len(els), "elements", nv, "verts", ni, "tris", round(os.path.getsize(f"{OUT}/{bid}.json") / 1e6, 2), "MB")

# ---- E1: 7개 모델 판정
e1 = []
for f, r in E1.items():
    e1.append(dict(file=f.split("/")[-1], schema=r["schema"], nphys=r["nphys"], level=r["level"], mode=r["mode"],
                   crs=r["crs"], classes=r["classes"], rules=r["results"],
                   bid=next((b for b, p in BASES.items() if p == f), None)))

# ---- E2: 결함 × 규칙
clean = {r["bid"]: r["res"] for r in E2 if r["mtype"] == "CLEAN" and "res" in r}
muts = []
mat = collections.defaultdict(collections.Counter)
for r in E2:
    if r["mtype"] == "CLEAN" or "res" not in r:
        continue
    det = sorted(detected_rules(clean[r["bid"]], r["res"]))
    for x in det:
        mat[r["mtype"]][x] += 1
    muts.append(dict(bid=r["bid"], m=r["mtype"], rep=r.get("rep"), log=r.get("log"), det=det,
                     primary=bool(set(det) & EXPECTED[r["mtype"]])))

summary = dict(e1=e1, e2=dict(mutants=muts, expected={k: sorted(v) for k, v in EXPECTED.items()}, matrix={k: dict(v) for k, v in mat.items()}, by_type=E2S["by_type"],
                                by_conf=E2S["by_conf"], clean=clean),
               e3=E3, plans=plans, th=qvf.TH, rules={k: list(v) for k, v in qvf.RULES.items()})
json.dump(summary, open(f"{OUT}/summary.json", "w"), ensure_ascii=False, separators=(",", ":"), default=str)
print("summary", round(os.path.getsize(f"{OUT}/summary.json") / 1e3), "KB")
