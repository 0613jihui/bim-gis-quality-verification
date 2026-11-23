"""대표 사례 그림 생성: 그림 3(4개 모델의 변환 결과 3D), 그림 4(공간참조 결함 전후 평면 비교)"""
import random, numpy as np, ifcopenshell, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.geometry import Polygon
import qvf, e2_mutation as E

# 한글 글꼴: Noto Sans CJK(리눅스) → 맑은 고딕(윈도우) → AppleGothic(맥) 순으로 사용
import os
_fonts = [("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK JP"),
          ("C:/Windows/Fonts/malgun.ttf", "Malgun Gothic"),
          ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", "AppleGothic")]
_family = "DejaVu Sans"
for _p, _name in _fonts:
    if os.path.exists(_p):
        font_manager.fontManager.addfont(_p); _family = _name; break
plt.rcParams.update({"font.family": _family, "font.size": 9, "axes.unicode_minus": False})

MAPPED, GENERIC, INVALID = "#9aa6b2", "#e8833a", "#c0392b"
CASES = [("B1", "Building-Architecture", "IFC4X3 · LoGeoRef 50 · 건축"),
         ("B2", "Building-Structural", "IFC4X3 · LoGeoRef 50 · 구조"),
         ("B3", "AC11-FZK-Haus", "IFC2X3 · LoGeoRef 40 · 건축(소형)"),
         ("B4", "AC20-Smiley-West", "IFC4 · LoGeoRef 40 · 건축(대형)")]

cache = {}
for bid, name, _ in CASES:
    m = ifcopenshell.open(E.BASES[bid]); g = qvf.georef_info(m); me = qvf.triangulate(m); ph = qvf.physical_elements(m)
    cache[bid] = (m, g, me, ph, qvf.convert(m, g, me, ph))
    print("loaded", bid, flush=True)

# ---------------- 그림 3
CONSTR, AUX = "#9aa6b2", "#6fa8dc"
AUXCLS = {"BuildingFurniture", "BuildingInstallation", "BridgeInstallation", "BridgeFurniture", "CityFurniture"}
fig = plt.figure(figsize=(10, 8.6))
for k, (bid, name, sub) in enumerate(CASES):
    m, g, me, ph, conv = cache[bid]
    T = conv["T"]; cls = {f["guid"]: f for f in conv["features"]}
    ax = fig.add_subplot(2, 2, k + 1, projection="3d")
    items = []; n_map = n_gen = n_inv = 0
    for e in ph:
        if e.id() not in me or not len(me[e.id()][1]):
            continue
        v, f = me[e.id()]; vm = T(v); rec = cls[e.GlobalId]
        if rec.get("solid_check") not in (None, "ok"):
            c = INVALID; n_inv += 1
        elif rec["cls"] == qvf.GENERIC:
            c = GENERIC; n_gen += 1
        else:
            c = AUX if rec["cls"] in AUXCLS else CONSTR; n_map += 1
        items.append((e, vm, f, c))
    core = [vm for e, vm, f, c in items if not e.is_a("IfcBuildingElementProxy")]
    V = np.vstack(core); lo, hi = V.min(0), V.max(0); pad = 0.03 * (hi - lo).max()
    hidden = 0
    for e, vm, f, c in items:
        ctr = vm.mean(0)
        if np.any(ctr[:2] < lo[:2] - pad) or np.any(ctr[:2] > hi[:2] + pad):
            hidden += 1; continue
        tri = vm[f]; nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
        lum = 0.55 + 0.45 * np.abs(nrm @ np.array([0.35, -0.45, 0.82]))
        base = np.array(matplotlib.colors.to_rgb(c)); a = 0.95 if c in (GENERIC, INVALID) else 0.5
        fc = np.c_[np.clip(base[None, :] * lum[:, None], 0, 1), np.full(len(tri), a)]
        ax.add_collection3d(Poly3DCollection(tri, facecolors=fc, edgecolors="none"))
    ax.set_xlim(lo[0] - pad, hi[0] + pad); ax.set_ylim(lo[1] - pad, hi[1] + pad); ax.set_zlim(lo[2], hi[2])
    rng = hi - lo; ax.set_box_aspect((rng[0], rng[1], max(rng[2], 0.12 * max(rng[:2]))))
    ax.view_init(elev=32, azim=(-20 if bid == "B4" else -60)); ax.set_axis_off()
    tot = n_map + n_gen + n_inv
    note = f" · 원점 표식 {hidden}개 화면 밖" if hidden else ""
    ax.set_title(f"({'abcd'[k]}) {bid} {name}\n{sub}\n매핑 {n_map}/{tot} · 일반객체 {n_gen} · 무효 솔리드 {n_inv}{note}", fontsize=9.5, pad=0)
    print(bid, n_map, n_gen, n_inv, hidden, flush=True)
from matplotlib.patches import Patch
fig.legend(handles=[Patch(color=CONSTR, label="구성요소로 매핑"), Patch(color=AUX, label="가구·설비·시설물로 매핑"),
                    Patch(color=GENERIC, label="GenericCityObject(매핑 실패)"), Patch(color=INVALID, label="무효 솔리드(R10)")],
           loc="lower center", ncol=4, frameon=False, fontsize=9.5)
plt.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.05, wspace=0.02, hspace=0.1)
fig.savefig("out/fig3_cases_3d.png", dpi=200)
print("fig3 ok", flush=True)

# ---------------- 그림 4: 공간참조 결함 전후 평면 비교 (B1, B2)
def fp_after(bid, mtype, **kw):
    m = ifcopenshell.open(E.BASES[bid]); E.mutate(m, mtype, random.Random(3), **kw)
    _, _, me, ph, _ = cache[bid]
    g = qvf.georef_info(m); conv = qvf.convert(m, g, me, ph, check_solids=False)
    return conv

def polys(geom):
    if geom is None: return []
    return [geom] if geom.geom_type == "Polygon" else [p for p in geom.geoms if p.geom_type == "Polygon"]

fig, axs = plt.subplots(1, 2, figsize=(10, 4.6))
for ax, bid, label in [(axs[0], "B1", "(a) B1 단독주택"), (axs[1], "B4", "(b) B4 대형 단지(10동)")]:
    m, g, me, ph, conv0 = cache[bid]
    rot = fp_after(bid, "M3_GEO_ROT", theta=1.0); sh = fp_after(bid, "M2_GEO_SHIFT", d=1.0)
    piv = conv0["T"](np.array([[c * g["unit"] for c in g["site_origin"]]]))[0] if g["mapconv"] is None else conv0["T"](np.zeros((1, 3)))[0]
    ref = {f["guid"]: f["footprint"] for f in conv0["facilities"]}
    devr = max(f["footprint"].hausdorff_distance(ref[f["guid"]]) for f in rot["facilities"] if f["guid"] in ref)
    devs = max(f["footprint"].hausdorff_distance(ref[f["guid"]]) for f in sh["facilities"] if f["guid"] in ref)
    allx = []
    for f in conv0["facilities"]:
        for p in polys(f["footprint"]):
            x, y = p.exterior.xy; ax.fill(x, y, color="#cfd6dd", lw=0); ax.plot(x, y, color="#6b7785", lw=0.8); allx += list(zip(x, y))
    for f in rot["facilities"]:
        for p in polys(f["footprint"]):
            x, y = p.exterior.xy; ax.plot(x, y, color="#1f6fd1", lw=1.3)
    for f in sh["facilities"]:
        for p in polys(f["footprint"]):
            x, y = p.exterior.xy; ax.plot(x, y, color="#e8833a", lw=1.3, ls="--")
    A = np.array(allx); cx, cy = A.mean(0)
    ax.plot(*piv[:2], marker="+", color="k", ms=10, mew=1.5)
    ax.annotate("변환 원점", piv[:2], xytext=(-8, 8), textcoords="offset points", fontsize=8.5, ha="right")
    ax.plot([piv[0], cx], [piv[1], cy], color="k", lw=0.6, ls=":")
    ax.set_aspect("equal"); ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=7)
    ax.set_xlabel(f"Easting (m, {conv0['crs']})", fontsize=8); ax.set_ylabel("Northing (m)", fontsize=8)
    ax.set_title(f"{label}: 회전 1° → {devr:.2f} m, 이동 1 m → {devs:.2f} m", fontsize=9.5)
from matplotlib.lines import Line2D
fig.legend(handles=[Patch(color="#cfd6dd", label="기준자료(결함 없음)"), Line2D([], [], color="#1f6fd1", lw=1.3, label="회전 1° 결함(M3)"),
                    Line2D([], [], color="#e8833a", lw=1.3, ls="--", label="원점 1 m 이동 결함(M2)")], loc="lower center", ncol=3, frameon=False)
plt.subplots_adjust(left=0.08, right=0.98, top=0.92, bottom=0.2, wspace=0.3)
fig.savefig("out/fig4_georef_faults.png", dpi=200)
print("fig4 ok")
