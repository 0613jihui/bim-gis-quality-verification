"""E3: severity sweep of georeferencing faults (translation / rotation) vs positional deviation (R14)"""
import json, math, random, pickle, numpy as np, ifcopenshell
import qvf, e2_mutation as E

ref = pickle.load(open("out/e1_reference.pkl", "rb"))["ref"]
D = [0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0]
TH = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]
rows = []
for bid in ["B1", "B2", "B3", "B4"]:
    f = E.BASES[bid]
    m0 = ifcopenshell.open(f)
    meshes = qvf.triangulate(m0)       # engineering geometry is unaffected by georef parameters
    phys = qvf.physical_elements(m0)
    g0 = qvf.georef_info(m0)
    conv0 = qvf.convert(m0, g0, meshes, phys, check_solids=False)
    # distance of facilities from the rotation pivot (map conversion origin / site origin) in map units
    T0 = conv0["T"]; pivot = T0(np.zeros((1, 3)))[0, :2] if g0["mapconv"] else T0(np.array([[c * g0["unit"] for c in g0["site_origin"]]]))[0, :2]
    rmax = max(np.max(np.linalg.norm(np.array(fa["footprint"].exterior.coords if fa["footprint"].geom_type == "Polygon" else
                                                   [c for p in fa["footprint"].geoms for c in p.exterior.coords]) - pivot, axis=1))
               for fa in conv0["facilities"] if fa["footprint"] is not None)
    for kind, vals in (("shift", D), ("rot", TH)):
        for v in vals:
            for sign in ([1] if kind == "shift" else [1, -1]):
                m = ifcopenshell.open(f)
                rng = random.Random(7)
                if kind == "shift":
                    E.mutate(m, "M2_GEO_SHIFT", rng, d=v)
                else:
                    g = qvf.georef_info(m)
                    th = math.radians(v) * sign; c, s_ = math.cos(th), math.sin(th)
                    if g["mapconv"] is not None:
                        mc = m.by_type("IfcMapConversion")[0]; a, b = mc.XAxisAbscissa or 1.0, mc.XAxisOrdinate or 0.0
                        mc.XAxisAbscissa, mc.XAxisOrdinate = a * c - b * s_, a * s_ + b * c
                    else:
                        ctx = [x for x in m.by_type("IfcGeometricRepresentationContext") if not x.is_a("IfcGeometricRepresentationSubContext") and x.TrueNorth][0]
                        a, b = ctx.TrueNorth.DirectionRatios[:2]; ctx.TrueNorth = m.createIfcDirection((a * c - b * s_, a * s_ + b * c))
                g = qvf.georef_info(m)
                conv = qvf.convert(m, g, meshes, phys, check_solids=False)
                r3 = qvf.stage_p3(m, conv, reference=ref[f])
                rows.append(dict(bid=bid, kind=kind, v=v, sign=sign, dev=r3["R14"]["value"], rmax=round(float(rmax), 2)))
                print(bid, kind, v, sign, r3["R14"]["value"], flush=True)
json.dump(rows, open("out/e3_sweep.json", "w"), indent=1)
