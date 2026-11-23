"""E2: fault-injection verification of the BG-QVF framework"""
import zlib, sys, json, math, random, pickle, time, glob, collections, traceback
import numpy as np, ifcopenshell, ifcopenshell.api.root, ifcopenshell.util.element as ue
from multiprocessing import Pool
from pyproj import Transformer
import qvf

BASES = {
    "B1": "bs43/Building-Architecture.ifc",
    "B2": "bs43/Building-Structural.ifc",
    "B3": "osb/AC11-FZK-Haus-IFC.ifc",
    "B4": "osb/AC-20-Smiley-West-10-Bldg_fix.ifc",
}
REPS = {"B1": 5, "B2": 5, "B3": 5, "B4": 3}
FRAC = 0.30
EXPECTED = {  # primary rules expected to detect each fault type
    "M1_GEO_DEL": {"R03"}, "M2_GEO_SHIFT": {"R14"}, "M3_GEO_ROT": {"R14"}, "M4_SCALE": {"R04", "R11"},
    "M5_CLASS": {"R05", "R09"}, "M6_PROP": {"R06"}, "M7_CONTAIN": {"R02"}, "M8_GUID": {"R08", "R12"},
    "M9_GEOM": {"R07", "R10"}, "M10_CRS": {"R13"},
}
WORSE = {  # direction in which the metric degrades
    "R01": +1, "R02": +1, "R03": -1, "R04": +1, "R05": +1, "R06": -1, "R07": -1, "R08": +1, "R09": -1,
    "R10": -1, "R11": +1, "R12": +1, "R13": 0, "R14": 0, "R15": 0, "R16": -1}


# ----------------------------------------------------------------------------- mutation operators
def ll_to_dms(x):
    s = -1 if x < 0 else 1; x = abs(x)
    d = int(x); mm = int((x - d) * 60); sec = (x - d - mm / 60) * 3600; si = int(sec); mic = int(round((sec - si) * 1e6))
    if mic == 1000000:
        si += 1; mic = 0
    return [s * d, s * mm, s * si, s * mic]


def mutate(m, mtype, rng, **kw):
    g = qvf.georef_info(m)
    phys = qvf.physical_elements(m)
    log = {}
    if mtype == "M1_GEO_DEL":
        if g["mapconv"] is not None:
            for x in m.by_type("IfcMapConversion") + m.by_type("IfcProjectedCRS"):
                m.remove(x)
            log["removed"] = "IfcMapConversion+IfcProjectedCRS"
        else:
            s = m.by_type("IfcSite")[0]; s.RefLatitude = None; s.RefLongitude = None
            log["removed"] = "IfcSite.RefLatitude/RefLongitude"
    elif mtype == "M2_GEO_SHIFT":
        d = kw.get("d", 1.0); phi = rng.uniform(0, 2 * math.pi)
        if g["mapconv"] is not None:
            mc = m.by_type("IfcMapConversion")[0]
            mc.Eastings += d * math.cos(phi); mc.Northings += d * math.sin(phi)
        else:
            lat, lon, _ = g["latlon"]; epsg = qvf.utm_epsg(lat, lon)
            f = Transformer.from_crs("EPSG:4326", epsg, always_xy=True); b = Transformer.from_crs(epsg, "EPSG:4326", always_xy=True)
            E, N = f.transform(lon, lat); lon2, lat2 = b.transform(E + d * math.cos(phi), N + d * math.sin(phi))
            s = m.by_type("IfcSite")[0]; s.RefLatitude = ll_to_dms(lat2); s.RefLongitude = ll_to_dms(lon2)
        log.update(d=d, phi=round(math.degrees(phi), 1))
    elif mtype == "M3_GEO_ROT":
        th = math.radians(kw.get("theta", 1.0)) * rng.choice([-1, 1])
        c, s_ = math.cos(th), math.sin(th)
        if g["mapconv"] is not None:
            mc = m.by_type("IfcMapConversion")[0]; a, b = mc.XAxisAbscissa or 1.0, mc.XAxisOrdinate or 0.0
            mc.XAxisAbscissa, mc.XAxisOrdinate = a * c - b * s_, a * s_ + b * c
        else:
            ctx = [x for x in m.by_type("IfcGeometricRepresentationContext") if not x.is_a("IfcGeometricRepresentationSubContext") and x.TrueNorth][0]
            a, b = ctx.TrueNorth.DirectionRatios[:2]
            ctx.TrueNorth = m.createIfcDirection((a * c - b * s_, a * s_ + b * c))
        log.update(theta_deg=round(math.degrees(th), 3))
    elif mtype == "M4_SCALE":
        if g["mapconv"] is not None:
            mc = m.by_type("IfcMapConversion")[0]; mc.Scale = (mc.Scale or 1.0) * 1000.0; log["scale"] = mc.Scale
        else:
            for u in m.by_type("IfcSIUnit"):
                if u.UnitType == "LENGTHUNIT":
                    u.Prefix = None if u.Prefix == "MILLI" else "MILLI"; log["prefix"] = u.Prefix
    elif mtype == "M5_CLASS":
        cand = [e for e in phys if not e.is_a("IfcBuildingElementProxy")]
        sel = [e.GlobalId for e in rng.sample(cand, max(1, int(round(FRAC * len(cand)))))]
        n = 0
        for gid in sel:
            try:
                e = m.by_guid(gid)
                ne = ifcopenshell.api.root.reassign_class(m, product=e, ifc_class="IfcBuildingElementProxy")
                if hasattr(ne, "PredefinedType"):
                    ne.PredefinedType = None   # realistic export: no carry-over of the old enumeration
                n += 1
            except Exception:
                pass
        for t in m.by_type("IfcBuildingElementProxyType"):
            if t.PredefinedType not in ("USERDEFINED", "NOTDEFINED", "COMPLEX", "ELEMENT", "PARTIAL", "PROVISIONFORVOID", "PROVISIONFORSPACE"):
                t.PredefinedType = "NOTDEFINED"
        log["n"] = n
    elif mtype == "M6_PROP":
        env = [e for e in phys if qvf.is_a_any(e, qvf.ENVELOPE)]
        cand = []
        for e in env:
            for r in getattr(e, "IsDefinedBy", []) or []:
                if r.is_a("IfcRelDefinesByProperties") and r.RelatingPropertyDefinition.is_a("IfcPropertySet") and \
                        any(p.Name == "IsExternal" for p in r.RelatingPropertyDefinition.HasProperties):
                    cand.append((e, r))
        if not cand:
            return None
        sel = rng.sample(cand, max(1, int(round(FRAC * len(cand)))))
        for e, r in sel:
            ps = r.RelatingPropertyDefinition
            if len(r.RelatedObjects) == 1 and len(ps.HasProperties) > 1:
                ps.HasProperties = tuple(p for p in ps.HasProperties if p.Name != "IsExternal")
            elif len(r.RelatedObjects) == 1:
                m.remove(r)
            else:
                r.RelatedObjects = tuple(o for o in r.RelatedObjects if o != e)
        log["n"] = len(sel)
    elif mtype == "M7_CONTAIN":
        cand = [e for e in phys if ue.get_container(e) is not None and ue.get_aggregate(e) is None]
        sel = rng.sample(cand, max(1, int(round(FRAC * len(cand)))))
        ids = {e.id() for e in sel}
        for r in m.by_type("IfcRelContainedInSpatialStructure"):
            keep = tuple(o for o in r.RelatedElements if o.id() not in ids)
            if len(keep) != len(r.RelatedElements):
                if keep:
                    r.RelatedElements = keep
                else:
                    m.remove(r)
        log["n"] = len(sel)
    elif mtype == "M8_GUID":
        a, b = rng.sample(phys, 2); b.GlobalId = a.GlobalId; log["guid"] = a.GlobalId
    elif mtype == "M9_GEOM":
        breps = [(e, i) for e in phys for i in qvf.body_items(e) if i.is_a("IfcFacetedBrep")]
        tess = [(e, i) for e in phys for i in qvf.body_items(e) if i.is_a("IfcTriangulatedFaceSet")]
        if breps:
            e, it = rng.choice(breps); sh = it.Outer
            faces = list(sh.CfsFaces); k = rng.randrange(len(faces))
            sh.CfsFaces = tuple(faces[:k] + faces[k + 1:]); log.update(kind="brep_face_removed", elem=e.GlobalId)
        elif tess:
            e, it = rng.choice(tess); ci = list(it.CoordIndex); k = rng.randrange(len(ci))
            it.CoordIndex = tuple(ci[:k] + ci[k + 1:]); log.update(kind="tess_triangle_removed", elem=e.GlobalId)
        else:
            return None
    elif mtype == "M10_CRS":
        if g["mapconv"] is None:
            return None
        crs = m.by_type("IfcProjectedCRS")[0]; log["from"] = crs.Name; crs.Name = "EPSG:5186"; log["to"] = crs.Name
    return log


# ----------------------------------------------------------------------------- evaluation
def detected_rules(clean, mut):
    det = set()
    for r, v in mut.items():
        c = clean.get(r, {})
        if v.get("passed") is False:
            if c.get("passed") is True or c.get("passed") is None:
                det.add(r)
            else:
                cv, mv, w = c.get("value"), v.get("value"), WORSE[r]
                try:
                    if w != 0 and cv is not None and mv is not None and (mv - cv) * w > 1e-9:
                        det.add(r)
                    elif w != 0 and cv is not None and mv is None:
                        det.add(r)
                except TypeError:
                    pass
    return det


def job(args):
    bid, mtype, rep, kw, ctx = args
    qvf.NPROC = 1
    rng = random.Random(zlib.crc32(f"{bid}|{mtype}|{rep}".encode()))
    t = time.time()
    try:
        m = ifcopenshell.open(BASES[bid])
        log = mutate(m, mtype, rng, **kw) if mtype != "CLEAN" else {}
        if log is None:
            return dict(bid=bid, mtype=mtype, rep=rep, skipped=True)
        res, conv, g = qvf.run(m, reference=ctx["ref"], context=ctx["context"])
        res = {k: {kk: (vv.item() if hasattr(vv, "item") else vv) for kk, vv in v.items() if kk != "detail"} for k, v in res.items()}
        return dict(bid=bid, mtype=mtype, rep=rep, kw=kw, log=log, res=res, sec=round(time.time() - t, 1))
    except Exception as ex:
        return dict(bid=bid, mtype=mtype, rep=rep, error=traceback.format_exc()[-600:])


if __name__ == "__main__":
    ref = pickle.load(open("out/e1_reference.pkl", "rb"))["ref"]
    # integration context: clean facilities from the other federated (bs43) models
    fed = ["bs43/Infra-Road.ifc", "bs43/Infra-Rail.ifc"]   # 통합 대상 GIS의 기존 도로·철도 레이어(R15 비교용)
    clean_fac = {}
    for f in fed:
        m = ifcopenshell.open(f); g = qvf.georef_info(m); me = qvf.triangulate(m); ph = qvf.physical_elements(m)
        clean_fac[f] = qvf.convert(m, g, me, ph)["facilities"]
    ctxs = {}
    for bid, f in BASES.items():
        context = [fa for o in fed for fa in clean_fac[o]] if f.startswith("bs43/") else None
        ctxs[bid] = dict(ref=ref[f], context=context)
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else list(BASES)
    jobs = []
    for bid in only:
        jobs.append((bid, "CLEAN", 0, {}, ctxs[bid]))
        for mt in EXPECTED:
            n = 1 if mt in ("M1_GEO_DEL", "M4_SCALE", "M10_CRS") else REPS[bid]
            for r in range(n):
                kw = {"d": 1.0} if mt == "M2_GEO_SHIFT" else ({"theta": 1.0} if mt == "M3_GEO_ROT" else {})
                jobs.append((bid, mt, r, kw, ctxs[bid]))
    print("jobs", len(jobs), flush=True)
    out = [r for r in (json.load(open("out/e2_raw.json")) if len(sys.argv) > 1 else []) if r["bid"] not in only]
    with Pool(2) as p:
        for i, r in enumerate(p.imap_unordered(job, jobs)):
            out.append(r)
            print(i, r["bid"], r["mtype"], r.get("rep"), r.get("sec"), "ERR" if "error" in r else ("skip" if r.get("skipped") else ""), flush=True)
            json.dump(out, open("out/e2_raw.json", "w"), ensure_ascii=False, default=str)
    print("done")
