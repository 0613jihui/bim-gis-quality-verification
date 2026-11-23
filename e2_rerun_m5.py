import json, pickle, glob, ifcopenshell
from multiprocessing import Pool
import qvf, e2_mutation as E
if __name__ == "__main__":
    ref = pickle.load(open("out/e1_reference.pkl", "rb"))["ref"]
    fed = sorted(glob.glob("bs43/*.ifc")); clean_fac = {}
    for f in fed:
        m = ifcopenshell.open(f); g = qvf.georef_info(m); me = qvf.triangulate(m); ph = qvf.physical_elements(m)
        clean_fac[f] = qvf.convert(m, g, me, ph)["facilities"]
    jobs = []
    for bid, f in E.BASES.items():
        ctx = dict(ref=ref[f], context=[fa for o in fed if o != f for fa in clean_fac[o]] if f.startswith("bs43/") else None)
        for r in range(E.REPS[bid]):
            jobs.append((bid, "M5_CLASS", r, {}, ctx))
    raw = [x for x in json.load(open("out/e2_raw.json")) if x["mtype"] != "M5_CLASS"]
    with Pool(2) as p:
        for r in p.imap_unordered(E.job, jobs):
            raw.append(r); print(r["bid"], r["rep"], r.get("sec"), "ERR" if "error" in r else "", flush=True)
    json.dump(raw, open("out/e2_raw.json", "w"), ensure_ascii=False, default=str)
