import glob, json, time, pickle, numpy as np, ifcopenshell
import qvf

FILES = sorted(glob.glob('bs43/Building-*.ifc')) + ['osb/AC11-FZK-Haus-IFC.ifc', 'osb/AC11-Institute-Var-2-IFC.ifc',
                                          'osb/AC-20-Smiley-West-10-Bldg_fix.ifc']
CONTROL = '3Fit2Fad92zf2f6aWdJtF5'   # shared 'geo-reference' object in the buildingSMART federated scene

out, cache = {}, {}
for f in FILES:
    t = time.time()
    m = ifcopenshell.open(f)
    g = qvf.georef_info(m)
    meshes = qvf.triangulate(m)
    phys = qvf.physical_elements(m)
    r1 = qvf.stage_p1(m, g, meshes, phys)
    conv = qvf.convert(m, g, meshes, phys)
    r2 = qvf.stage_p2(conv)
    cache[f] = dict(m=m, g=g, conv=conv, r1=r1, r2=r2, meshes=meshes, t=time.time() - t,
                    nphys=len(phys), schema=m.schema)
    print(f, round(time.time() - t, 1), 's', flush=True)

# federated scene: control-object consistency + inter-facility topology
fed = [f for f in FILES if f.startswith('bs43/')]
# 통합 대상 GIS의 기존 도로·철도 레이어(분석 대상 아님, R15 비교용)
CTX = []
for f in ['bs43/Infra-Road.ifc', 'bs43/Infra-Rail.ifc']:
    m = ifcopenshell.open(f); g = qvf.georef_info(m); me = qvf.triangulate(m); ph = qvf.physical_elements(m)
    CTX += qvf.convert(m, g, me, ph, check_solids=False)['facilities']
ctrl = {}
for f in fed:
    c = cache[f]
    for ft in c['conv']['features']:
        if ft['guid'] == CONTROL and 'bbox' in ft:
            b = np.array(ft['bbox']); ctrl[f] = (b[:3] + b[3:]) / 2
ctrl_med = np.median(np.array(list(ctrl.values())), axis=0)
ctrl_dev = {f: float(np.linalg.norm(v[:2] - ctrl_med[:2])) for f, v in ctrl.items()}
print('control deviations', ctrl_dev)

for f in FILES:
    c = cache[f]
    m = c['m']
    if f in fed:
        context = CTX
        r3 = qvf.stage_p3(m, c['conv'], reference=None, context=context, controls=None)
        if f in ctrl_dev:
            d = ctrl_dev[f]
            r3['R14'] = dict(value=round(d, 4), passed=d <= qvf.TH['R14_tau'], detail='공통기준객체 편차(연합모델 중앙값 대비)')
    else:
        r3 = qvf.stage_p3(m, c['conv'])
    res = {**c['r1'], **c['r2'], **r3}
    out[f] = dict(schema=c['schema'], nphys=c['nphys'], level=c['g']['level'], mode=c['conv']['mode'],
                  crs=c['conv']['crs'], seconds=round(c['t'], 1),
                  facilities=[(fa['type'], fa['name'], round(fa['zmax'] - fa['zmin'], 2),
                               round(fa['footprint'].area, 1) if fa['footprint'] is not None else None)
                              for fa in c['conv']['facilities']],
                  classes=dict(__import__('collections').Counter(ft['cls'] for ft in c['conv']['features'])),
                  results={k: {kk: (vv if not isinstance(vv, (np.floating, np.bool_)) else vv.item()) for kk, vv in v.items()}
                           for k, v in res.items()})
    try:
        qvf.to_cityjson(c['conv'], 'out/' + f.split('/')[-1].replace('.ifc', '.city.json'))
    except Exception as ex:
        print('cityjson fail', f, ex)

json.dump(out, open('out/e1_results.json', 'w'), ensure_ascii=False, indent=1, default=str)
# cache clean conversions for E2 reference
ref = {f: {fa['guid']: fa['footprint'] for fa in cache[f]['conv']['facilities']} for f in FILES}
pickle.dump(dict(ref=ref, ctrl_med=ctrl_med), open('out/e1_reference.pkl', 'wb'))
for f, o in out.items():
    print(f.split('/')[-1], o['schema'], o['nphys'], o['mode'],
          ' '.join(f"{k}:{'P' if v['passed'] else ('-' if v['passed'] is None else 'F')}" for k, v in o['results'].items()))
