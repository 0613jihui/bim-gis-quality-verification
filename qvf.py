"""
BIM-GIS Quality Verification Framework (BG-QVF) - reference implementation
3 stages (P1 source BIM, P2 conversion, P3 GIS integration) x ISO 19157-1 quality elements.
"""
import math, json, collections, multiprocessing, warnings
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue, ifcopenshell.validate
import trimesh, shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from pyproj import CRS, Transformer

warnings.filterwarnings("ignore")
NPROC = multiprocessing.cpu_count()

# ----------------------------------------------------------------------------- thresholds
TH = dict(
    R01_max_schema_errors=0,
    R02_max_uncontained=0.0,
    R03_min_logeoref=50,
    R04_scale_tol=1e-3,
    R05_max_proxy_ratio=0.10,
    R06_min_isexternal=0.95,
    R07_min_triangulated=1.0,
    R09_min_mapping=0.90,
    R10_min_solid_valid=0.95,
    R11_height=(0.5, 1000.0), R11_area=(1.0, 1.0e6), R11_ratio_tol=2e-3,
    R14_tau=0.20,          # m, positional tolerance (design parameter)
    R15_max_overlap=1.0,   # m2
    R16_min_meta=1.0,
)

RULES = {  # id: (stage, ISO 19157-1 element, description)
    "R01": ("P1", "논리일관성-형식", "IFC 스키마 적합성"),
    "R02": ("P1", "논리일관성-개념", "공간구조 귀속 완전성"),
    "R03": ("P1", "공간참조(확장)", "LoGeoRef 수준"),
    "R04": ("P1", "논리일관성-정의역", "지도변환 축척·단위 정합"),
    "R05": ("P1", "주제정확도-분류", "일반객체(Proxy) 비율"),
    "R06": ("P1", "완전성-누락", "외피 판별 속성(IsExternal) 완전성"),
    "R07": ("P1", "논리일관성-형식", "형상 해석(삼각망화) 성공률"),
    "R08": ("P1", "논리일관성-개념", "GlobalId 유일성"),
    "R09": ("P2", "주제정확도-분류", "CityGML 3.0 의미 매핑률"),
    "R10": ("P2", "논리일관성-위상", "솔리드 형상 유효성(ISO 19107)"),
    "R11": ("P2", "논리일관성-정의역", "변환 형상 타당성(규모·축척)"),
    "R12": ("P2", "논리일관성-개념", "BIM-GIS 식별자 연계 무결성"),
    "R13": ("P3", "논리일관성-정의역", "좌표참조계 적용범위 적합성"),
    "R14": ("P3", "위치정확도-절대/상대", "기준자료 대비 위치편차"),
    "R15": ("P3", "논리일관성-위상", "이종 시설물 간 중첩"),
    "R16": ("P3", "사용적합성-계보", "메타데이터 완전성"),
}

FACILITY_TYPES = ("IfcBuilding", "IfcBridge", "IfcRoad", "IfcRailway", "IfcTunnel", "IfcMarineFacility", "IfcFacility")
SOLID_REP = {"SweptSolid", "AdvancedSweptSolid", "Brep", "AdvancedBrep", "CSG", "Clipping"}
ENVELOPE = ("IfcWall", "IfcSlab", "IfcRoof", "IfcWindow", "IfcDoor", "IfcCurtainWall")
CONSTRUCTIVE = ("IfcWall", "IfcCurtainWall", "IfcSlab", "IfcRoof", "IfcColumn", "IfcBeam", "IfcMember", "IfcPlate",
                "IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight", "IfcRailing", "IfcDoor", "IfcWindow",
                "IfcCovering", "IfcFooting", "IfcPile", "IfcChimney", "IfcShadingDevice", "IfcBearing",
                "IfcBuildingElementPart")
FURNITURE = ("IfcFurnishingElement", "IfcFurniture", "IfcSystemFurnitureElement")
GENERIC = "GenericCityObject"


# ----------------------------------------------------------------------------- helpers
def is_a_any(e, types):
    return any(e.is_a(t) for t in types)


def physical_elements(m):
    out = []
    for e in m.by_type("IfcElement"):
        if e.is_a("IfcFeatureElementSubtraction") or e.is_a("IfcVirtualElement"):
            continue
        if not e.Representation:
            continue
        out.append(e)
    return out


def facility_of(e):
    p, seen = e, 0
    while p is not None and seen < 20:
        if is_a_any(p, FACILITY_TYPES):
            return p
        p = ue.get_parent(p); seen += 1
    return None


def unit_to_m(m):
    for u in m.by_type("IfcSIUnit"):
        if u.UnitType == "LENGTHUNIT":
            return {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, None: 1.0, "KILO": 1e3}.get(u.Prefix, 1.0)
    for u in m.by_type("IfcConversionBasedUnit"):
        if u.UnitType == "LENGTHUNIT":
            v = u.ConversionFactor.ValueComponent.wrappedValue
            return v
    return 1.0


def dms(v):
    if not v:
        return None
    sgn = -1 if any(x < 0 for x in v) else 1
    v = [abs(x) for x in v] + [0, 0, 0, 0]
    return sgn * (v[0] + v[1] / 60 + v[2] / 3600 + v[3] / 3.6e9)


# ----------------------------------------------------------------------------- georeferencing
def georef_info(m):
    g = dict(levels=[], unit=unit_to_m(m), mapconv=None, crs=None, latlon=None, truenorth=None, site_origin=(0, 0, 0))
    addr = [s for s in m.by_type("IfcSite") + m.by_type("IfcBuilding")
            if getattr(s, "SiteAddress", None) or getattr(s, "BuildingAddress", None)]
    if addr:
        g["levels"].append(10)
    sites = m.by_type("IfcSite")
    if sites and sites[0].RefLatitude and sites[0].RefLongitude:
        lat, lon = dms(sites[0].RefLatitude), dms(sites[0].RefLongitude)
        if lat is not None and lon is not None and not (abs(lat) < 1e-9 and abs(lon) < 1e-9):
            g["latlon"] = (lat, lon, sites[0].RefElevation or 0.0)
            g["levels"].append(20)
    if sites and sites[0].ObjectPlacement:
        try:
            loc = sites[0].ObjectPlacement.RelativePlacement.Location.Coordinates
            g["site_origin"] = tuple(list(loc) + [0] * (3 - len(loc)))
            if any(abs(c) > 0 for c in loc):
                g["levels"].append(30)
        except Exception:
            pass
    for c in m.by_type("IfcGeometricRepresentationContext"):
        if c.is_a("IfcGeometricRepresentationSubContext"):
            continue
        if c.TrueNorth is not None:
            g["truenorth"] = tuple(c.TrueNorth.DirectionRatios[:2])
            g["levels"].append(40)
            break
    if m.schema != "IFC2X3":
        mc = m.by_type("IfcMapConversion")
        if mc:
            x = mc[0]
            tc = x.TargetCRS
            g["mapconv"] = dict(E=x.Eastings, N=x.Northings, H=x.OrthogonalHeight or 0.0,
                                a=x.XAxisAbscissa if x.XAxisAbscissa is not None else 1.0,
                                b=x.XAxisOrdinate if x.XAxisOrdinate is not None else 0.0,
                                S=x.Scale if x.Scale is not None else 1.0)
            g["crs"] = tc.Name if tc else None
            if tc is not None:
                g["levels"].append(50)
    g["level"] = max(g["levels"]) if g["levels"] else 0
    return g


def utm_epsg(lat, lon):
    z = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + z}"


def make_transform(g):
    """returns (fn(xyz_m)->map xyz, crs_name, mode) or (None,None,'none')"""
    u = g["unit"]
    if g["mapconv"] is not None and g["crs"]:
        mc = g["mapconv"]
        n = math.hypot(mc["a"], mc["b"]) or 1.0
        a, b, S = mc["a"] / n, mc["b"] / n, mc["S"]
        f = S / u  # metres(geom) -> project units -> map units

        def T(P):
            P = np.asarray(P, float)
            x, y, z = P[:, 0], P[:, 1], P[:, 2]
            return np.c_[mc["E"] + f * (a * x - b * y), mc["N"] + f * (b * x + a * y), mc["H"] + f * z]
        return T, g["crs"], "LoGeoRef50"
    if g["latlon"] is not None:
        lat, lon, h = g["latlon"]
        epsg = utm_epsg(lat, lon)
        E0, N0 = Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform(lon, lat)
        tn = g["truenorth"] or (0.0, 1.0)
        nn = math.hypot(*tn) or 1.0
        nx, ny = tn[0] / nn, tn[1] / nn
        ox, oy, oz = [c * u for c in g["site_origin"]]

        def T(P):
            P = np.asarray(P, float)
            x, y, z = P[:, 0] - ox, P[:, 1] - oy, P[:, 2] - oz
            return np.c_[E0 + (ny * x - nx * y), N0 + (nx * x + ny * y), h + z]
        return T, epsg, "LoGeoRef20(approx.)"
    return None, None, "none"


# ----------------------------------------------------------------------------- geometry
def triangulate(m):
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    meshes, failed = {}, []
    it = ifcopenshell.geom.iterator(s, m, NPROC)
    if it.initialize():
        while True:
            sh = it.get()
            v = np.array(sh.geometry.verts, float).reshape(-1, 3)
            f = np.array(sh.geometry.faces, int).reshape(-1, 3)
            meshes[sh.id] = (v, f)
            if not it.next():
                break
    return meshes


def body_rep_type(e):
    try:
        for r in e.Representation.Representations:
            if r.RepresentationIdentifier in ("Body", None) and r.RepresentationType:
                if r.RepresentationType == "MappedRepresentation":
                    mi = r.Items[0].MappingSource.MappedRepresentation
                    return mi.RepresentationType
                return r.RepresentationType
    except Exception:
        pass
    return None


def is_closed_tess(e):
    try:
        for r in e.Representation.Representations:
            for it in r.Items:
                if it.is_a("IfcMappedItem"):
                    it = it.MappingSource.MappedRepresentation.Items[0]
                if it.is_a("IfcTessellatedFaceSet") and getattr(it, "Closed", None):
                    return True
    except Exception:
        pass
    return False


def body_items(e):
    out = []
    try:
        for r in e.Representation.Representations:
            if r.RepresentationIdentifier not in ("Body", None):
                continue
            for it in r.Items:
                if it.is_a("IfcMappedItem"):
                    out += list(it.MappingSource.MappedRepresentation.Items)
                else:
                    out.append(it)
    except Exception:
        pass
    return out


_ISET = ifcopenshell.geom.settings()


def element_solid_valid(e, v, f):
    """single-item element: check element mesh (incl. openings);
       multi-item element: check each constituent solid separately (MultiSolid semantics)"""
    its = body_items(e)
    if len(its) <= 1:
        return mesh_valid(v, f)
    for it in its:
        try:
            sh = ifcopenshell.geom.create_shape(_ISET, it)
            vv = np.array(sh.verts, float).reshape(-1, 3); ff = np.array(sh.faces, int).reshape(-1, 3)
        except Exception:
            return False, "item_fail"
        ok, why = mesh_valid(vv, ff)
        if not ok:
            return False, "item_" + why
    return True, "ok"


def mesh_valid(v, f):
    if len(f) == 0:
        return False, "empty"
    t = trimesh.Trimesh(v, f, process=True)
    if not t.is_watertight:
        return False, "not_closed"
    if not t.is_winding_consistent:
        return False, "orientation"
    if t.volume <= 1e-9:
        return False, "nonpositive_volume"
    return True, "ok"


def footprint(v, f):
    tris = v[f][:, :, :2]
    d1, d2 = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    ar = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0])
    polys = list(shapely.polygons(tris[ar > 1e-10]))
    if not polys:
        return None
    u = unary_union([p.buffer(1e-4, join_style=2) for p in polys])
    return u.buffer(-1e-4, join_style=2)


# ----------------------------------------------------------------------------- semantic mapping
def citygml_class(e, fac):
    ft = fac.is_a() if fac is not None else None
    if e.is_a("IfcBuildingElementProxy"):
        return GENERIC
    if e.is_a("IfcGeographicElement"):
        pt = getattr(e, "PredefinedType", None)
        return {"TERRAIN": "TINRelief", "VEGETATION": "SolitaryVegetationObject"}.get(pt, GENERIC)
    if e.is_a("IfcSign") or e.is_a("IfcSignal"):
        return "CityFurniture"
    if ft == "IfcRoad" and is_a_any(e, ("IfcCourse", "IfcPavement", "IfcKerb", "IfcSurfaceFeature", "IfcEarthworksFill")):
        return "Road"
    if ft == "IfcRailway" and is_a_any(e, ("IfcCourse", "IfcTrackElement", "IfcRail", "IfcEarthworksFill")):
        return "Railway"
    if ft == "IfcBridge":
        if e.is_a("IfcRailing"):
            return "BridgeInstallation"
        if is_a_any(e, CONSTRUCTIVE + ("IfcMember",)):
            return "BridgeConstructiveElement"
        if is_a_any(e, FURNITURE):
            return "BridgeFurniture"
    if ft == "IfcBuilding":
        if is_a_any(e, CONSTRUCTIVE):
            return "BuildingConstructiveElement"
        if is_a_any(e, FURNITURE):
            return "BuildingFurniture"
        if e.is_a("IfcDistributionElement") or e.is_a("IfcDiscreteAccessory") or e.is_a("IfcFlowTerminal"):
            return "BuildingInstallation"
    if is_a_any(e, FURNITURE):
        return "CityFurniture"
    return GENERIC


# ----------------------------------------------------------------------------- stage P1
def stage_p1(m, g, meshes, phys):
    R = {}
    # R01 schema
    lg = ifcopenshell.validate.json_logger()
    try:
        ifcopenshell.validate.validate(m, lg)
        nerr = len(lg.statements)
    except Exception as ex:
        nerr = 999
    R["R01"] = dict(value=nerr, passed=nerr <= TH["R01_max_schema_errors"])
    # R02 containment
    unc = [e for e in phys if ue.get_container(e) is None and ue.get_aggregate(e) is None and ue.get_nest(e) is None]
    r = len(unc) / max(1, len(phys))
    R["R02"] = dict(value=round(r, 4), passed=r <= TH["R02_max_uncontained"], detail=len(unc))
    # R03 LoGeoRef
    R["R03"] = dict(value=g["level"], passed=g["level"] >= TH["R03_min_logeoref"], detail=sorted(set(g["levels"])))
    # R04 scale/unit consistency of map conversion
    if g["mapconv"] is not None:
        eff = g["mapconv"]["S"] / g["unit"]
        ok = abs(eff - 1.0) <= TH["R04_scale_tol"]
        R["R04"] = dict(value=round(eff, 6), passed=ok)
    else:
        R["R04"] = dict(value=None, passed=None, detail="N/A (no IfcMapConversion)")
    # R05 proxy ratio
    px = sum(1 for e in phys if e.is_a("IfcBuildingElementProxy"))
    r = px / max(1, len(phys))
    R["R05"] = dict(value=round(r, 4), passed=r <= TH["R05_max_proxy_ratio"], detail=px)
    # R06 IsExternal completeness (building envelope classes only)
    env = [e for e in phys if is_a_any(e, ENVELOPE) and (facility_of(e) is None or facility_of(e).is_a("IfcBuilding"))]
    if env:
        has = 0
        for e in env:
            ps = ue.get_psets(e)
            if any("IsExternal" in d for k, d in ps.items() if k and k.startswith("Pset_") and k.endswith("Common")):
                has += 1
        r = has / len(env)
        R["R06"] = dict(value=round(r, 4), passed=r >= TH["R06_min_isexternal"], detail=f"{has}/{len(env)}")
    else:
        R["R06"] = dict(value=None, passed=None, detail="N/A (no envelope elements)")
    # R07 triangulation success
    ok = sum(1 for e in phys if e.id() in meshes and len(meshes[e.id()][1]) > 0)
    r = ok / max(1, len(phys))
    R["R07"] = dict(value=round(r, 4), passed=r >= TH["R07_min_triangulated"], detail=f"{ok}/{len(phys)}")
    # R08 GUID uniqueness
    guids = [p.GlobalId for p in m.by_type("IfcRoot")]
    dup = len(guids) - len(set(guids))
    R["R08"] = dict(value=dup, passed=dup == 0)
    return R


# ----------------------------------------------------------------------------- stage P2 (conversion)
def convert(m, g, meshes, phys, check_solids=True):
    T, crs, mode = make_transform(g)
    objs, feats, valid_stats = {}, [], collections.Counter()
    fac_geoms = collections.defaultdict(list)
    eng_fp = collections.defaultdict(list)
    for e in phys:
        fac = facility_of(e)
        cls = citygml_class(e, fac)
        rec = dict(guid=e.GlobalId, ifc=e.is_a(), cls=cls, name=e.Name,
                   facility=(fac.is_a(), fac.GlobalId, fac.Name) if fac is not None else None)
        if e.id() in meshes and len(meshes[e.id()][1]):
            v, f = meshes[e.id()]
            rt = body_rep_type(e)
            if check_solids and (rt in SOLID_REP or is_closed_tess(e)):
                ok, why = element_solid_valid(e, v, f)
                rec["solid_check"] = why
                valid_stats["checked"] += 1
                valid_stats["valid"] += ok
            if fac is not None:
                eng_fp[fac.GlobalId].append((v, f))
            if T is not None:
                vm = T(v)
                rec["bbox"] = [*vm.min(0).round(3).tolist(), *vm.max(0).round(3).tolist()]
                if fac is not None:
                    fac_geoms[(fac.GlobalId, fac.is_a(), fac.Name)].append((vm, f))
        feats.append(rec)
    # facility level LoD1 (Building, Bridge) / LoD0 (Road, Railway, other)
    facilities = []
    for (fg, ft, fn), parts in fac_geoms.items():
        V = np.vstack([p[0] for p in parts]); off = 0; F = []
        for vv, ff in parts:
            F.append(ff + off); off += len(vv)
        F = np.vstack(F)
        fp = footprint(V, F)
        if fp is not None:
            fp = fp.simplify(1e-3)
        fpe = None
        pe = eng_fp.get(fg)
        if pe:
            Ve = np.vstack([p[0] for p in pe]); off = 0; Fe = []
            for vv, ff in pe:
                Fe.append(ff + off); off += len(vv)
            fpe = footprint(Ve, np.vstack(Fe))
            fpe = fpe.simplify(1e-3) if fpe is not None else None
        zmin, zmax = float(V[:, 2].min()), float(V[:, 2].max())
        rec = dict(guid=fg, type=ft, name=fn, footprint=fp, eng_area=fpe.area if fpe is not None else None,
                   zmin=zmin, zmax=zmax, lod=1 if ft in ("IfcBuilding", "IfcBridge") else 0)
        if rec["lod"] == 1 and fp is not None and not fp.is_empty:
            polys = [fp] if isinstance(fp, Polygon) else list(getattr(fp, "geoms", []))
            sol_ok = True
            for p in polys:
                if p.area < 1e-6:
                    continue
                try:
                    sm = trimesh.creation.extrude_polygon(p, max(zmax - zmin, 1e-6))
                    ok, _ = mesh_valid(sm.vertices, sm.faces)
                    sol_ok &= ok
                except Exception:
                    sol_ok = False
            rec["lod1_valid"] = sol_ok
        facilities.append(rec)
    return dict(features=feats, facilities=facilities, crs=crs, mode=mode, T=T, valid_stats=valid_stats)


def stage_p2(conv):
    R = {}
    feats = conv["features"]
    mapped = sum(1 for f in feats if f["cls"] != GENERIC)
    r = mapped / max(1, len(feats))
    R["R09"] = dict(value=round(r, 4), passed=r >= TH["R09_min_mapping"], detail=f"{mapped}/{len(feats)}")
    vs = conv["valid_stats"]
    lod1 = [f for f in conv["facilities"] if f["lod"] == 1]
    lod1_ok = all(f.get("lod1_valid", False) for f in lod1)
    if vs["checked"]:
        r = vs["valid"] / vs["checked"]
        R["R10"] = dict(value=round(r, 4), passed=(r >= TH["R10_min_solid_valid"]) and lod1_ok,
                        detail=f"elem {vs['valid']}/{vs['checked']}, LoD1 {'ok' if lod1_ok else 'invalid'}")
    else:
        R["R10"] = dict(value=None, passed=lod1_ok if lod1 else None, detail="no solid elements")
    # R11 plausibility of converted facilities
    if conv["T"] is None:
        R["R11"] = dict(value=None, passed=False, detail="변환 불가(좌표참조 없음)")
    else:
        bad = []
        for f in conv["facilities"]:
            h = f["zmax"] - f["zmin"]
            a = f["footprint"].area if f["footprint"] is not None else 0.0
            ratio = a / f["eng_area"] if f["eng_area"] else 1.0
            okh = TH["R11_height"][0] <= h <= TH["R11_height"][1] if f["lod"] == 1 else h <= TH["R11_height"][1]
            oka = TH["R11_area"][0] <= a <= TH["R11_area"][1]
            okr = abs(ratio - 1) <= TH["R11_ratio_tol"]
            if not (okh and oka and okr):
                bad.append((f["name"], round(h, 2), round(a, 1), round(ratio, 4)))
        R["R11"] = dict(value=len(bad), passed=len(bad) == 0, detail=bad[:3])
    # R12 identifier linkage
    ids = [f["guid"] for f in feats]
    dup = len(ids) - len(set(ids))
    miss = sum(1 for i in ids if not i)
    R["R12"] = dict(value=dup + miss, passed=(dup + miss) == 0)
    return R


# ----------------------------------------------------------------------------- stage P3 (integration)
def crs_area_check(conv):
    if conv["T"] is None or conv["crs"] is None:
        return False, "좌표참조 없음"
    try:
        crs = CRS.from_user_input(conv["crs"])
    except Exception:
        return False, f"CRS 해석 불가: {conv['crs']}"
    aou = crs.area_of_use
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    pts = []
    for f in conv["features"]:
        if "bbox" in f:
            b = f["bbox"]; pts += [(b[0], b[1]), (b[3], b[4])]
    if not pts:
        return False, "좌표 없음"
    P = np.array(pts)
    lon, lat = tr.transform(P[:, 0], P[:, 1])
    lon, lat = np.asarray(lon), np.asarray(lat)
    inside = np.isfinite(lon) & np.isfinite(lat) & (lon >= aou.west - 1e-6) & (lon <= aou.east + 1e-6) & \
             (lat >= aou.south - 1e-6) & (lat <= aou.north + 1e-6)
    r = inside.mean()
    return bool(r == 1.0), f"{r:.3f} in [{aou.west:.0f},{aou.south:.0f},{aou.east:.0f},{aou.north:.0f}]"


def footprint_deviation(fa, fb):
    """centroid offset and Hausdorff distance between two footprints"""
    if fa is None or fb is None or fa.is_empty or fb.is_empty:
        return None, None
    c = fa.centroid.distance(fb.centroid)
    h = fa.hausdorff_distance(fb)
    return c, h


def stage_p3(m, conv, reference=None, context=None, controls=None):
    """reference: dict facility guid->footprint (reference spatial data);
       context: list of facility dicts from other datasets to integrate;
       controls: dict guid->expected map centroid (shared control objects)"""
    R = {}
    ok, det = crs_area_check(conv)
    R["R13"] = dict(value=ok, passed=ok, detail=det)
    # R14
    devs = []
    if reference:
        for f in conv["facilities"]:
            if f["guid"] in reference:
                c, h = footprint_deviation(f["footprint"], reference[f["guid"]])
                if h is not None:
                    devs.append(h)
    if controls is not None and conv["T"] is not None:
        for guid, (exp, mesh_c) in controls.items():
            devs.append(float(np.linalg.norm(conv["T"](mesh_c[None, :])[0, :2] - exp[:2])))
    if conv["T"] is None:
        R["R14"] = dict(value=None, passed=False, detail="좌표참조 없음")
    elif devs:
        mx = max(devs)
        R["R14"] = dict(value=round(mx, 4), passed=mx <= TH["R14_tau"], detail=f"n={len(devs)}")
    elif reference is not None and reference:
        R["R14"] = dict(value=None, passed=False, detail="기준객체 대응 실패")
    else:
        R["R14"] = dict(value=None, passed=None, detail="N/A (기준자료 없음)")
    # R15 overlap building vs transport facilities
    allf = list(conv["facilities"]) + list(context or [])
    bld = [f for f in allf if f["type"] == "IfcBuilding" and f["footprint"] is not None]
    trn = [f for f in allf if f["type"] in ("IfcRoad", "IfcRailway") and f["footprint"] is not None]
    ov = 0.0
    for b in bld:
        for t in trn:
            if b["guid"] == t["guid"]:
                continue
            ov = max(ov, b["footprint"].intersection(t["footprint"]).area)
    if bld and trn:
        R["R15"] = dict(value=round(ov, 3), passed=ov <= TH["R15_max_overlap"])
    else:
        R["R15"] = dict(value=None, passed=None, detail="N/A (비교 대상 없음)")
    # R16 metadata completeness
    h = m.header.file_name
    items = [bool(h.time_stamp), bool(h.originating_system),
             bool([x for x in (h.author or []) if x]) or bool([x for x in (h.organization or []) if x]),
             conv["crs"] is not None, bool(m.by_type("IfcSIUnit") or m.by_type("IfcConversionBasedUnit"))]
    r = sum(items) / len(items)
    R["R16"] = dict(value=round(r, 2), passed=r >= TH["R16_min_meta"], detail=items)
    return R


# ----------------------------------------------------------------------------- full pipeline
def run(m, reference=None, context=None, controls=None, meshes=None, stages=("P1", "P2", "P3")):
    g = georef_info(m)
    if meshes is None:
        meshes = triangulate(m)
    phys = physical_elements(m)
    res = {}
    res.update(stage_p1(m, g, meshes, phys))
    conv = convert(m, g, meshes, phys)
    res.update(stage_p2(conv))
    res.update(stage_p3(m, conv, reference, context, controls))
    return res, conv, g


def to_cityjson(conv, path):
    """write the converted dataset as CityJSON 2.0 (LoD1/LoD0 facilities + element bboxes as attributes)"""
    cj = {"type": "CityJSON", "version": "2.0", "transform": {"scale": [0.001, 0.001, 0.001], "translate": [0, 0, 0]},
          "metadata": {"referenceSystem": f"https://www.opengis.net/def/crs/EPSG/0/{conv['crs'].split(':')[-1]}" if conv["crs"] else None},
          "CityObjects": {}, "vertices": []}
    if conv["facilities"]:
        allv = []
        for f in conv["facilities"]:
            if f["footprint"] is not None:
                allv.append(np.array(f["footprint"].bounds[:2]))
        tr = np.min(allv, 0) if allv else np.zeros(2)
        cj["transform"]["translate"] = [float(tr[0]), float(tr[1]), 0.0]
    V = cj["vertices"]

    def addv(x, y, z):
        V.append([int(round((x - cj["transform"]["translate"][0]) / 0.001)),
                  int(round((y - cj["transform"]["translate"][1]) / 0.001)), int(round(z / 0.001))])
        return len(V) - 1
    tmap = {"IfcBuilding": "Building", "IfcBridge": "Bridge", "IfcRoad": "Road", "IfcRailway": "Railway"}
    for f in conv["facilities"]:
        fp = f["footprint"]
        if fp is None or fp.is_empty:
            continue
        polys = [fp] if isinstance(fp, Polygon) else [p for p in getattr(fp, "geoms", []) if isinstance(p, Polygon)]
        surfaces = []
        for p in polys:
            ring = list(p.exterior.coords)[:-1]
            if f["lod"] == 1:
                bot = [addv(x, y, f["zmin"]) for x, y in ring]
                top = [addv(x, y, f["zmax"]) for x, y in ring]
                surfaces.append([bot[::-1]]); surfaces.append([top])
                for i in range(len(ring)):
                    j = (i + 1) % len(ring)
                    surfaces.append([[bot[i], bot[j], top[j], top[i]]])
            else:
                surfaces.append([[addv(x, y, f["zmin"]) for x, y in ring]])
        geom = ({"type": "MultiSolid", "lod": "1", "boundaries": [[[s] for s in surfaces]]} if False else
                {"type": "MultiSurface", "lod": str(f["lod"]), "boundaries": surfaces})
        cj["CityObjects"][f["guid"]] = {"type": tmap.get(f["type"], "GenericCityObject"),
                                        "attributes": {"ifc_guid": f["guid"], "name": f["name"]}, "geometry": [geom]}
    for e in conv["features"]:
        if e["guid"] in cj["CityObjects"]:
            continue
        cj["CityObjects"][e["guid"]] = {"type": e["cls"] if e["cls"] != GENERIC else "GenericCityObject",
                                        "attributes": {"ifc_guid": e["guid"], "ifc_class": e["ifc"], "name": e["name"],
                                                       "bbox": e.get("bbox")}}
    with open(path, "w") as fh:
        json.dump(cj, fh)
