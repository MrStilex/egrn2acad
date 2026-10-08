"""Выписки ЕГРН и ГПЗУ (PDF) -> скрипт AutoCAD (.scr) с границами земельных участков.

Использование:
  - перетащить один или несколько PDF на egrn2acad.exe (ЕГРН и ГПЗУ можно вперемешку)
  - или запустить exe без аргументов: обработает все PDF в своей папке
Тип документа определяется автоматически.
Результат: EGRN_<дата_время>.scr рядом с первым PDF. В AutoCAD: команда SCRIPT -> выбрать файл.
"""
import datetime
import glob
import os
import re
import sys

import pdfplumber

VERSION = "1.1.1"

BANNER = f"""==============================================
 egrn2acad {VERSION} — выписки ЕГРН и ГПЗУ → AutoCAD
 Автор: Анвар
 Telegram: @melt28
=============================================="""

POINT_RE = re.compile(r"^(\d+)\s+(\d{6}(?:\.\d+)?)\s+(\d{7}(?:\.\d+)?)(?:\s|$)")
SECTION_32_RE = re.compile(r"Лист № \d+ раздела 3\.2 ")


def collect_contours(lines):
    contours, cur = [], []
    for line in lines:
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
    return contours


def parse_egrn(pdf):
    kn, doc_area, lines = None, None, []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if kn is None:
            m = re.search(r"Кадастровый номер:\s*(\d+:\d+:\d+:\d+)", text)
            kn = m and m.group(1)
        if doc_area is None:
            m = re.search(r"Площадь:\s*([\d.]+)", text)
            doc_area = m and float(m.group(1))
        if SECTION_32_RE.search(text):
            lines += text.split("\n")
    return kn, doc_area, collect_contours(lines)


def parse_gpzu(pdf):
    # координаты границы — в начале документа, между «Описание границ…» и «Кадастровый номер…»
    text = "\n".join(page.extract_text() or "" for page in pdf.pages[:4])
    start = text.find("Описание границ земельного участка")
    end = text.find("Кадастровый номер земельного участка", start)
    if start < 0 or end < 0:
        return None, None, []
    tail = text[end:]
    m = re.search(r"территории\s+(\S+)\s*\n\s*Площадь", tail)
    kn = m and m.group(1)
    m = re.search(r"Площадь земельного участка\s*([\d ]+(?:[.,]\d+)?)\s*м", tail)
    doc_area = m and float(m.group(1).replace(" ", "").replace(",", "."))
    return kn, doc_area, collect_contours(text[start:end].split("\n"))


DOC_TYPES = {"EGRN": ("ЕГРН", parse_egrn), "GPZU": ("ГПЗУ", parse_gpzu)}


def parse(path):
    """Возвращает (тип документа, кадастровый номер, площадь из документа, контуры [(n, x, y), ...])."""
    with pdfplumber.open(path) as pdf:
        first = pdf.pages[0].extract_text() or ""
        if "Выписка из Единого государственного реестра недвижимости" in first:
            kind = "EGRN"
        elif "Градостроительный план земельного участка" in first:
            kind = "GPZU"
        else:
            return None, None, None, []
        return (kind, *DOC_TYPES[kind][1](pdf))


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
            kind, kn, doc_area, contours = parse(path)
        except Exception as e:
            report.append(f"!! {name}: не удалось прочитать PDF ({e})")
            continue
        if kind is None:
            report.append(f"!! {name}: не похоже на выписку ЕГРН или ГПЗУ — пропущен")
            continue
        label = DOC_TYPES[kind][0]
        if not contours:
            report.append(f"!! {name} ({label}): не найдены координаты границ участка")
            continue
        kn = kn or os.path.splitext(name)[0]
        calc = sum(area(c) for c in contours)
        if doc_area is None:
            status, note = "!!", f"площадь в {label} не найдена"
        elif abs(calc - doc_area) <= max(1.0, doc_area * 0.001):
            status, note = "OK", f"{label} {doc_area:g}"
        else:
            status, note = "!!", f"{label} {doc_area:g} — НЕ СОВПАДАЕТ, проверьте участок"
        report.append(f"{status} {label} {kn}: контуров {len(contours)}, площадь по координатам {calc:.1f} м² ({note})")
        lines += ["_.-LAYER", "_M", f"{kind}_" + re.sub(r'[<>/\\":;?*|,=`\s]+', "-", kn), ""]
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
    print(BANNER + "\n")
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    pdfs = [a for a in argv if a.lower().endswith(".pdf")] or sorted(glob.glob(os.path.join(base, "*.pdf")))
    if not pdfs:
        print("PDF-файлы не найдены. Перетащите выписки ЕГРН или ГПЗУ на значок программы.")
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
