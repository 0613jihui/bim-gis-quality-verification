# 건축물 BIM–GIS 연계 데이터의 단계별 품질 검증 체계(BG-QVF)

논문 「건설정보–공간정보 연계 데이터의 단계별 품질 검증 체계 설계 연구 -건축물을 대상으로-」(한국콘텐츠학회논문지 투고 원고)의
검증 체계 구현 코드, 실험 스크립트, 변환 결과와 실험 원자료입니다.

BG-QVF는 IFC 건물 모델을 CityGML 3.0(CityJSON 2.0)으로 옮겨 GIS에 통합하는 과정을 세 단계로 나누어 검사합니다.

| 단계 | 내용 | 규칙 |
|---|---|---|
| P1 원천 BIM 검증 | 스키마, 식별자, 공간참조(LoGeoRef), 분류, 속성, 솔리드 | R01–R08 |
| P2 변환 검증 | 의미 매핑률, 솔리드 유효성, 형상 타당 범위, 식별자 연계 | R09–R12 |
| P3 통합 검증 | 좌표계 적용범위, 기준자료 대비 위치편차, 기존 레이어와의 중첩, 메타데이터 | R13–R16 |

R14(위치편차)는 기준자료의 종류에 따라 두 방법으로 측정합니다. E1의 buildingSMART 분야 모델 4개는 공통 기준객체 중심의 평면 위치를 연합모델 중앙값과 비교하고, E2·E3는 기준 모델과 변이 모델의 건물 외곽선 사이 Hausdorff 거리를 씁니다.

![BG-QVF 구조](docs/figures/fig1_framework.png)

## 검증 뷰어

**https://0613jihui.github.io/bim-gis-quality-verification/viewer/** 에서 설치 없이 실험 결과를 볼 수 있습니다.

- 모델 검사(E1): 7개 모델 × 16개 규칙 판정표, 대표 모델 B1–B4의 3D 부재별 판정(어느 부재가 어떤 규칙에 걸렸는지)과 GIS 변환 결과(LoD1) 비교
- 결함 주입(E2): 검사 단계별 탐지율, 결함 10종 × 규칙 16개 탐지 행렬, 변이 모델 131개의 결함 내용과 탐지 규칙
- 공간참조 민감도(E3): 원점 이동·진북 회전을 직접 넣어 보며 위치편차(R14)를 계산하는 평면도와 회전각별 편차 그래프

뷰어 데이터(`docs/viewer/data/`)는 실험을 마친 뒤 `python viewer_export.py`로 다시 만들 수 있습니다.

## 폴더 구성

```
qvf.py              검사 규칙 16개(P1/P2/P3)와 IFC → CityGML 3.0(CityJSON) 변환기
e1_analysis.py      E1  공개 건물 IFC 7종 분석(IV장), CityJSON 출력
e2_mutation.py      E2  결함 주입 실험 M1–M10(V장 1–2절)
e2_analyze.py       E2  결과 집계(결함 유형별·검사 구성별·기준 모델별)
e3_sweep.py         E3  원점 이동·회전 민감도(V장 3절)
fig_cases.py        그림 2와 보조 그림(결함 전후 평면) 생성
extra_checks.py     기본 출력에 저장되지 않는 본문 수치 재현
e2_rerun_m5.py      기록용(아래 '참고' 참조)
download_data.py    실험 데이터 9개를 고정 커밋에서 내려받고 SHA-256 확인
validate_cityjson.py  출력 CityJSON 7개를 공식 스키마(2.0.2)로 검사하고 LoD1 솔리드가 닫혔는지 확인
viewer_export.py    검증 뷰어용 데이터 추출 → docs/viewer/data/
out/                실험 원자료(JSON), 변환 결과(*.city.json), 그림 파일
docs/figures/       논문 그림
docs/viewer/        검증 뷰어(웹 페이지와 데이터)
```

## 논문 표·그림과 파일의 대응

| 논문 | 생성 스크립트 | 결과 파일 |
|---|---|---|
| 표 3 공개 건물 데이터 7종의 규칙별 판정 결과 | e1_analysis.py | out/e1_results.json |
| 그림 2 대표 사례 4종의 변환 결과 | e1_analysis.py → fig_cases.py | out/fig3_cases_3d.png, out/*.city.json |
| 표 4 주입 결함과 탐지 결과 | e2_mutation.py → e2_analyze.py | out/e2_raw.json → out/e2_summary.json (`by_type`) |
| 표 5 검사 구성별 탐지율 | e2_analyze.py | out/e2_summary.json (`by_conf`) |
| 그림 3 회전 오류에 따른 위치편차 | e3_sweep.py | out/e3_sweep.json |
| 그림 4 검증 결과 시각화 서비스 화면 | viewer_export.py | docs/viewer/ |
| 본문 보조 수치(τ 민감도, 임계 회전각 등) | extra_checks.py | out/extra_checks.json |
| (보조) 공간참조 결함 전후 평면 | fig_cases.py | out/fig4_georef_faults.png |

그림 1(체계 구조)은 개념도로, 코드로 생성하지 않습니다. 결과 파일 이름의 번호(fig3, fig4)는 이전 원고 기준이며, 재현 스크립트와의 호환을 위해 그대로 두었습니다.

`out/e1_results.json`의 `seconds`는 모델별 P1·P2 처리 시간(형상 해석, P1 검사, 변환, P2 검사)이며, 실행 환경에 따라 달라집니다.

## 실험 데이터

모두 공개 건물 IFC입니다. `download_data.py`가 논문 실험에 쓴 것과 같은 커밋에서 내려받아 해시를 확인합니다.

| 기호 | 파일 | 출처 | 역할 |
|---|---|---|---|
| B1 | Building-Architecture.ifc | buildingSMART Sample-Test-Files, IFC 4.3.2.0 Simple-Scene (CC BY 4.0) | 분석·결함 주입 |
| B2 | Building-Structural.ifc | 〃 | 분석·결함 주입 |
| – | Building-Hvac.ifc, Building-Landscaping.ifc | 〃 | 분석 |
| – | Infra-Road.ifc, Infra-Rail.ifc | 〃 | R15 비교용 기존 도로·철도 레이어(분석 대상 아님) |
| B3 | AC11-FZK-Haus-IFC.ifc | opensourceBIM TestFiles, TestData/data | 분석·결함 주입 |
| – | AC11-Institute-Var-2-IFC.ifc | 〃 | 분석 |
| B4 | AC-20-Smiley-West-10-Bldg_fix.ifc | 〃 | 분석·결함 주입 |

- buildingSMART: https://github.com/buildingSMART/Sample-Test-Files (commit `5030f65`)
- opensourceBIM: https://github.com/opensourceBIM/TestFiles (commit `2fdf948`). 라이선스가 명시되어 있지 않아 원본 IFC는 이 저장소에 넣지 않았습니다.

## 실행 방법

Python 3.11 이상(실험은 3.13에서 수행).

```bash
git clone https://github.com/0613jihui/bim-gis-quality-verification.git
cd bim-gis-quality-verification
python -m venv .venv && source .venv/bin/activate      # 윈도우: .venv\Scripts\activate
pip install -r requirements.txt
python download_data.py                                # bs43/, osb/ 폴더 생성

python e1_analysis.py      # 약 2분
python validate_cityjson.py # 출력 파일 적합성 확인(CityJSON 공식 스키마를 내려받음)
python e2_mutation.py      # 가장 오래 걸림(131개 변이 모델). B1,B2처럼 기준 모델만 지정해 다시 실행 가능
python e2_analyze.py
python e3_sweep.py
python fig_cases.py
python extra_checks.py
```

모든 스크립트는 저장소 최상위 폴더에서 실행합니다. `out/`의 결과 파일은 덮어써지며,
`e1_analysis.py`를 다시 실행했을 때 실행 시간(`seconds`) 외의 값은 저장된 결과와 같음을 확인했습니다.

## 실험 환경

ifcopenshell 0.9.0, shapely 2.2, trimesh 5.2, pyproj 3.8(PROJ 9.8), mapbox_earcut 2.1, numpy 2.5, matplotlib 3.11

## 주요 결과 요약

- E1: 7개 모델 × 16개 규칙 112개 조합 중 98건을 판정, 20건(20.4%) 불합격. 나머지 14건은 해당 없음 5건(검사 대상이 없음), 판정 불가 9건(필요한 자료가 없음)
- E2: 변이 모델 131개 중 109개(83.2%) 탐지. 스키마 검증만으로는 13.7%, P3 통합 검증 추가로 +25.2%p
- E3: 1° 회전 시 위치 편차 B1 0.21 m, B4 1.32 m. τ = 0.20 m 기준 임계 회전각은 0.15–1.16°

## 참고

결함 M5(분류 손실)는 초기 실행에서 재분류 후 기존 PredefinedType이 남아 스키마 위반이 함께 발생했습니다.
PredefinedType을 정리하도록 `e2_mutation.py`를 고친 뒤 M5만 다시 실행했으며, `out/e2_raw.json`과 논문 수치는 수정 후 결과입니다.
`e2_rerun_m5.py`는 그 재실행 과정을 남긴 기록용 스크립트입니다.

판정 상태는 통과·불합격·해당 없음(`status: "NA"`, 검사할 대상이 모델에 없음)·판정 불가(`status: "ND"`, 판정에 필요한 자료가 없음)의 네 가지입니다.
출력 CityJSON은 건물을 LoD1 Solid로, 부재를 형상 없는 하위 객체(parents로 건물에 연결)로 저장합니다. 초기 버전은 부재의 parents가 빠지고 LoD1을 MultiSurface로 내보내 7개 중 6개가 공식 스키마를 통과하지 못했으나, 수정 후 7개 모두 통과합니다. R09·R10은 변환기 내부의 클래스 할당과 형상(IFC 부재 솔리드, 내부에서 생성한 LoD1 솔리드)을 검사하며, 최종 파일의 형식 적합성은 validate_cityjson.py로 따로 확인합니다.
초기 버전은 건물이 없는 모델(Building-Landscaping)의 R11을 "통과"로 집계했으나, 검사 대상이 없으므로 "해당 없음"으로 고쳤습니다(판정 99건 → 98건).

## 사용한 오픈소스

| 도구 | 버전 | 용도 | 인용 |
|---|---|---|---|
| [IfcOpenShell](https://ifcopenshell.org) | 0.9.0 | IFC 읽기, 형상 삼각망화, 스키마 검증 | 논문 [32] |
| [Shapely](https://github.com/shapely/shapely) | 2.2 | 평면 윤곽, 중첩, Hausdorff 거리 | [33] |
| [trimesh](https://trimesh.org) | 5.2 | 솔리드 유효성, LoD1 압출 | [34] |
| [pyproj](https://pyproj4.github.io/pyproj/) / [PROJ](https://proj.org) | 3.8 / 9.8 | 좌표 변환 (PROJ DOI: 10.5281/zenodo.5884394) | [35] [36] |
| [NumPy](https://numpy.org) | 2.5 | 수치 계산 | [37] |
| [Matplotlib](https://matplotlib.org) | 3.11 | 그림 2·4 | [38] |
| [three.js](https://threejs.org) | r128 | 검증 뷰어의 3D 표시 | [39] |
| [CityJSON](https://www.cityjson.org) | 2.0 | 변환 결과 형식 | [31] |

## 라이선스

이 저장소의 코드와 문서는 [MIT 라이선스](LICENSE)를 따릅니다.
실험에 사용한 원본 IFC와 그로부터 변환한 결과(`out/*.city.json`)에는 원본 데이터의 조건이 함께 적용됩니다.
buildingSMART 모델은 CC BY 4.0이며, opensourceBIM 모델(AC11-FZK-Haus, AC11-Institute-Var-2, AC-20-Smiley-West)은
원본 저장소에 라이선스가 명시되어 있지 않아 해당 변환 결과는 연구 재현 목적으로만 제공합니다.
