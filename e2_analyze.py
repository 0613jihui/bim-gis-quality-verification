import json, collections
from e2_mutation import EXPECTED, detected_rules
raw = json.load(open("out/e2_raw.json"))
errs = [r for r in raw if "error" in r]
print("errors", len(errs))
for e in errs[:3]:
    print(e["bid"], e["mtype"], e["error"][-300:])
clean = {r["bid"]: r["res"] for r in raw if r["mtype"] == "CLEAN" and "res" in r}
P1 = {f"R{i:02d}" for i in range(1, 9)}; P2 = {f"R{i:02d}" for i in range(9, 13)}; P3 = {f"R{i:02d}" for i in range(13, 17)}
CONF = {"B0 스키마 검증(R01)": {"R01"}, "P1 단독": P1, "P1+P2": P1 | P2, "P1+P2+P3(제안)": P1 | P2 | P3}
rows = []
for r in raw:
    if r["mtype"] == "CLEAN" or "res" not in r:
        continue
    det = detected_rules(clean[r["bid"]], r["res"])
    rows.append(dict(bid=r["bid"], mt=r["mtype"], det=det, primary=bool(det & EXPECTED[r["mtype"]])))
skipped = [(r["bid"], r["mtype"]) for r in raw if r.get("skipped")]
print("skipped", sorted(set(skipped)))
# false alarm on clean: rerun determinism -> clean vs clean = none by construction; report clean failing rules
for b, c in clean.items():
    print("clean", b, [k for k, v in c.items() if v["passed"] is False])
out = {"by_type": {}, "by_conf": {}, "by_base": {}}
print("\n유형 | n | 탐지 | 주규칙 | 연쇄 규칙(빈도)")
for mt in EXPECTED:
    rs = [x for x in rows if x["mt"] == mt]
    if not rs:
        continue
    n = len(rs); d = sum(1 for x in rs if x["det"]); p = sum(1 for x in rs if x["primary"])
    casc = collections.Counter(k for x in rs for k in x["det"] - EXPECTED[mt])
    first = collections.Counter(("P1" if x["det"] & P1 else "P2" if x["det"] & P2 else "P3" if x["det"] & P3 else "-") for x in rs)
    bases = sorted(set(x["bid"] for x in rs))
    conf = {c: sum(1 for x in rs if x["det"] & S) for c, S in CONF.items()}
    out["by_type"][mt] = dict(n=n, det=d, primary=p, cascade=dict(casc), first=dict(first), bases=bases, conf=conf,
                              by_base={b: (sum(1 for x in rs if x["bid"] == b and x["det"]), sum(1 for x in rs if x["bid"] == b)) for b in bases})
    print(mt, n, d, p, dict(casc), dict(first), conf, out["by_type"][mt]["by_base"])
N = len(rows)
for c, S in CONF.items():
    k = sum(1 for x in rows if x["det"] & S)
    out["by_conf"][c] = (k, N)
    print(c, k, N, round(k / N * 100, 1))
print("primary overall", sum(x["primary"] for x in rows), N)
json.dump(out, open("out/e2_summary.json", "w"), ensure_ascii=False, indent=1)
