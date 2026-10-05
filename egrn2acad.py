"""Выписки ЕГРН (PDF) -> скрипт AutoCAD (.scr) с границами земельных участков.

Использование:
  - перетащить один или несколько PDF на egrn2acad.exe
  - или запустить exe без аргументов: обработает все PDF в своей папке
Результат: EGRN_<дата_время>.scr рядом с первым PDF. В AutoCAD: команда SCRIPT -> выбрать файл.
"""
import datetime
import glob
import os
import re
import sys

import pdfplumber

VERSION = "1.0.0"

POINT_RE = re.compile(r"^(\d+)\s+(\d{6}(?:\.\d+)?)\s+(\d{7}(?:\.\d+)?)(?:\s|$)")
SECTION_32_RE = re.compile(r"Лист № \d+ раздела 3\.2 ")


def parse(path):
    """Возвращает (кадастровый номер, площадь из ЕГРН, список контуров [(n, x, y), ...])."""
    kn, egrn_area, contours, cur = None, None, [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if kn is None:
                m = re.search(r"Кадастровый номер:\s*(\d+:\d+:\d+:\d+)", text)
                kn = m and m.group(1)
            if egrn_area is None:
                m = re.search(r"Площадь:\s*([\d.]+)", text)
                egrn_area = m and float(m.group(1))
            if not SECTION_32_RE.search(text):
                continue
            for line in text.split("\n"):
                m = POINT_RE.match(line)
                if not m:
                    continue
                pt = (int(m.group(1)), float(m.group(2)), float(m.group(3)))
                # контур закрыт, когда снова встречается его первая точка
                if cur and pt[0] == cur[0][0] and pt[1:] == cur[0][1:]:
                    contours.append(cur)
                    cur = []
                else:
                    cur.append(pt)
    if cur:
        contours.append(cur)
    return kn, egrn_area, contours


def area(contour):
    pts = [(x, y) for _, x, y in contour]
    pts.append(pts[0])
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:]))) / 2


def build_script(pdfs):
    lines = ['(setq _egrn_os (getvar "OSMODE"))', '(setvar "OSMODE" 0)']
    report, drawn = [], 0
    for path in pdfs:
        name = os.path.basename(path)
        try:
            kn, egrn_area, contours = parse(path)
        except Exception as e:
            report.append(f"!! {name}: не удалось прочитать PDF ({e})")
            continue
        if not kn or not contours:
            report.append(f"!! {name}: не найдены координаты границ (раздел 3.2)")
            continue
        calc = sum(area(c) for c in contours)
        if egrn_area is None:
            status, note = "!!", "площадь в выписке не найдена"
        elif abs(calc - egrn_area) <= max(1.0, egrn_area * 0.001):
            status, note = "OK", f"ЕГРН {egrn_area:g}"
        else:
            status, note = "!!", f"ЕГРН {egrn_area:g} — НЕ СОВПАДАЕТ, проверьте участок"
        report.append(f"{status} {kn}: контуров {len(contours)}, площадь по координатам {calc:.1f} м² ({note})")
        lines += ["_.-LAYER", "_M", "EGRN_" + kn.replace(":", "-"), ""]
        for c in contours:
            lines.append("_.PLINE")
            lines += [f"{y:.2f},{x:.2f}" for _, x, y in c]
            lines.append("_C")
        drawn += 1
    lines += ['(setvar "OSMODE" _egrn_os)', "_.ZOOM _E"]
    return "\n".join(lines) + "\n", report, drawn


def main(argv):
    if "--version" in argv:
        print(f"egrn2acad {VERSION}")
        return 0
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    pdfs = [a for a in argv if a.lower().endswith(".pdf")] or sorted(glob.glob(os.path.join(base, "*.pdf")))
    if not pdfs:
        print("PDF-файлы не найдены. Перетащите выписки ЕГРН на значок программы.")
        return 1
    script, report, drawn = build_script(pdfs)
    print("\n".join(report))
    if not drawn:
        print("\nНичего не нарисовано, файл не создан.")
        return 1
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = os.path.join(os.path.dirname(os.path.abspath(pdfs[0])), f"EGRN_{stamp}.scr")
    with open(out, "w", encoding="cp1251", newline="\r\n") as f:
        f.write(script)
    print(f"\nГотово: {out}\nВ AutoCAD: команда SCRIPT -> выберите этот файл.")
    return 0


if __name__ == "__main__":
    code = main(sys.argv[1:])
    if getattr(sys, "frozen", False) and "--version" not in sys.argv:
        input("\nНажмите Enter, чтобы закрыть окно...")
    sys.exit(code)
