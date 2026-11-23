"""실험에 사용한 공개 IFC 9개를 고정 커밋에서 내려받아 bs43/, osb/ 폴더에 저장하고 SHA-256을 확인한다.

사용법:  python download_data.py
원본 저장소
  - buildingSMART Sample-Test-Files (CC BY 4.0), commit 5030f652e85d3e679b392fcb38bfa3328d6d9f79
  - opensourceBIM TestFiles, commit 2fdf94854a7fba814a17604ed65f543f125cd265
    (opensourceBIM 파일은 라이선스가 명시되어 있지 않아 이 저장소에 직접 포함하지 않는다)
"""
import hashlib
import os
import sys
import urllib.parse
import urllib.request

BSST = ("https://raw.githubusercontent.com/buildingSMART/Sample-Test-Files/"
        "5030f652e85d3e679b392fcb38bfa3328d6d9f79/IFC 4.3.2.0 (IFC 4.3 ADD2)/Simple-Scene/")
OSB = ("https://raw.githubusercontent.com/opensourceBIM/TestFiles/"
       "2fdf94854a7fba814a17604ed65f543f125cd265/TestData/data/")

FILES = [
    # (저장 위치, 원본 URL 기준, 파일명, sha256)
    ("bs43", BSST, "Building-Architecture.ifc", "96e7103812b15b65eb1fd7802d36b9962833485dce5ead4f440bbf529530881d"),
    ("bs43", BSST, "Building-Hvac.ifc", "22891586f153793d098811caec8a510cd404f6c2f1979fb329eeeebc3f475642"),
    ("bs43", BSST, "Building-Landscaping.ifc", "93253acebf6c2d9bfeb1300c3c8d2fdf663ea24746e5cddb8392aaf50f9a0ca8"),
    ("bs43", BSST, "Building-Structural.ifc", "db64895488aad4eab082c8292f5632145b0fc864c0642d4fe667404882bacf27"),
    ("bs43", BSST, "Infra-Road.ifc", "a3cb29433d7176bd31ff7535a596b5d7cd4eb7f2fb0eb6eee451612063c1f167"),
    ("bs43", BSST, "Infra-Rail.ifc", "c9073051e17796b8b59f96cf268207f4011c08eedeaa791774480c33e9defbb3"),
    ("osb", OSB, "AC11-FZK-Haus-IFC.ifc", "c89069da241e149166e0551128aaf088def582a48c267e67a08ca88c3f1319a0"),
    ("osb", OSB, "AC11-Institute-Var-2-IFC.ifc", "3556ecbc39ae94c03ad9efcd87ffdbd66f45ed5f769f03ddc1ecc3ef8c26877e"),
    ("osb", OSB, "AC-20-Smiley-West-10-Bldg_fix.ifc", "f75f1e8b1a37840db7540e7855f51776f8d653f4af2e6d068cdd88bcde456c9d"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    bad = 0
    for folder, base, name, digest in FILES:
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, name)
        if not (os.path.exists(dest) and sha256(dest) == digest):
            url = urllib.parse.quote(base + name, safe=":/")
            print(f"다운로드: {name}")
            urllib.request.urlretrieve(url, dest)
        ok = sha256(dest) == digest
        bad += not ok
        print(f"  {'OK ' if ok else '불일치'}  {dest}")
    if bad:
        sys.exit(f"{bad}개 파일의 해시가 논문 실험에 사용한 파일과 다릅니다.")
    print("모든 파일이 논문 실험에 사용한 파일과 동일합니다.")


if __name__ == "__main__":
    main()
