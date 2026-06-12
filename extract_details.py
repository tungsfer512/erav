#!/usr/bin/env python3
"""
Tải trang chi tiết ERAVCertificatorDisplay.aspx?DocId=<id> cho từng Id trong ids.json,
trích xuất các trường ở tab 1 + danh sách giấy tờ (link /Public) ở tab 2,
rồi ghi mảng object vào details.json.

YÊU CẦU: phiên đăng nhập còn hiệu lực.
  -> Lưu request "Copy as cURL" của 1 trang chi tiết (khi đang đăng nhập) vào erav/detail.sh
     Script tự lấy cookie + headers tươi từ đó.

Cách dùng:
  python3 extract_details.py --demo        # chỉ làm thử Id đầu tiên, in kết quả + lưu HTML mẫu
  python3 extract_details.py --dump         # in cấu trúc HTML trang mẫu (giúp dò selector)
  python3 extract_details.py                # chạy toàn bộ -> details.json
"""

import os
import re
import sys
import json
import time
import shlex
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
DETAIL_SH = os.path.join(HERE, "detail.sh")     # cURL trang chi tiết (đăng nhập)
PAGE_SH = os.path.join(HERE, "page.sh")          # fallback (thường đã hết hạn)
IDS_JSON = os.path.join(HERE, "ids.json")
CACHE_DIR = os.path.join(HERE, "html", "detail") # cache HTML thô từng DocId
OUT_JSON = os.path.join(HERE, "details.json")

DELAY = 0.6
TIMEOUT = 60
MAX_RETRY = 4

# Ánh xạ trường tab 1 -> (kiểu, hậu tố id của phần tử chứa GIÁ TRỊ)
#   "span"  : lấy text của <span>
#   "input" : lấy thuộc tính value của <input>
#   "date"  : lấy value của <input> rồi đổi YYYY-MM-DD... -> dd/MM/yyyy
TAB1_FIELDS = [
    ("Trạng thái",                         "span",  "lblStatus"),
    ("Số giấy phép",                       "input", "txtCertificateLicense"),
    ("Ngày cấp phép",                      "date",  "radDpkCertificateDate_dateInput"),
    ("Tên tổ chức đề nghị",                "span",  "lblcompanyName"),
    ("Cơ quan trực tiếp (nếu có)",         "span",  "lblSuperiors"),
    ("Trụ sở giao dịch chính",             "span",  "lblAddress"),
    ("Số điện thoại",                      "span",  "lblNumPhone"),
    ("Số Fax",                             "span",  "lblNumFax"),
    ("Mã số thuế",                         "span",  "lblTaxCode"),
    ("Số giấy đăng ký doanh nghiệp",       "span",  "lblCompanyRegisterCode"),
    ("Ngày cấp giấy đăng ký doanh nghiệp", "span",  "lblCompanyRegisterDate"),
    ("Ngành nghề kinh doanh hiện tại",     "span",  "lblCompanyTypeName"),
]

# link file thật nằm ở .../Public/...  (khác hẳn menu /PublicServices/)
PUBLIC_MARK = "/Public/"


# ----------------------- đọc request từ cURL -----------------------
def parse_curl(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().replace("\\\n", " ")
    tokens = shlex.split(text)
    url = cookie = None
    headers = {}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-H", "--header"):
            k, _, v = tokens[i + 1].partition(":")
            headers[k.strip()] = v.strip()
            i += 2
        elif t in ("-b", "--cookie"):
            cookie = tokens[i + 1]
            i += 2
        elif t.startswith("http"):
            url = t
            i += 1
        else:
            i += 1
    # cookie có thể nằm trong header 'Cookie'
    if not cookie:
        for k in list(headers):
            if k.lower() == "cookie":
                cookie = headers.pop(k)
    return url, headers, cookie


def build_url_template(sample_url):
    """Từ URL mẫu (có DocId=...), tạo hàm sinh URL theo docid."""
    parts = urlsplit(sample_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))

    def make(docid):
        q["DocId"] = str(docid)
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(q), parts.fragment))
    return make


def is_login(html):
    return ("txtPassword" in html) or ("txtCaptcha" in html)


# ----------------------- trích xuất -----------------------
def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _by_id_suffix(soup, name, suffix):
    """Tìm phần tử <name> có id kết thúc bằng suffix (id ASP.NET có tiền tố cố định)."""
    return soup.find(name, id=lambda x: x and x.endswith(suffix))


def _fmt_date(v):
    """'2026-06-05-00-00-00' -> '05/06/2026'. Nếu không khớp, trả nguyên."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else _clean(v)


def get_field(soup, kind, suffix):
    if kind == "span":
        el = _by_id_suffix(soup, "span", suffix)
        return _clean(el.get_text(" ")) if el else ""
    if kind == "input":
        el = _by_id_suffix(soup, "input", suffix)
        return _clean(el.get("value")) if el else ""
    if kind == "date":
        el = _by_id_suffix(soup, "input", suffix)
        return _fmt_date(el.get("value")) if el else ""
    return ""


def extract_files(soup):
    """
    Lấy giấy tờ ở tab 2: duyệt từng hàng <tr class="certificate-items-item">,
    lấy link <a> có '/Public/' (file tải về) + tên ở ô txtFileName (cột Giấy tờ).
    """
    files = []
    seen = set()
    for tr in soup.select("tr.certificate-items-item"):
        link = tr.find("a", href=lambda h: h and PUBLIC_MARK in h)
        if not link:
            continue
        href = link["href"].strip()
        if href in seen:
            continue
        seen.add(href)

        # tên = giá trị ô txtFileName (RadInput) trong cùng hàng
        name = ""
        inp = tr.find("input", id=lambda x: x and x.endswith("txtFileName"))
        if inp and inp.get("value"):
            name = _clean(inp["value"])
        if not name:
            wrap = tr.find(id=lambda x: x and x.endswith("txtFileName_wrapper"))
            if wrap:
                name = _clean(wrap.get_text(" "))
        if not name:
            name = _clean(link.get_text(" "))

        files.append({"Tên file": name, "Đường dẫn": href})
    return files


def parse_detail(html):
    soup = BeautifulSoup(html, "lxml")
    obj = {}
    for label, kind, suffix in TAB1_FIELDS:
        obj[label] = get_field(soup, kind, suffix)
    obj["files"] = extract_files(soup)
    return obj


def dump_structure(html):
    """In cấu trúc để dò selector khi cần."""
    soup = BeautifulSoup(html, "lxml")
    print("=== span/div/label CÓ id (id -> text) ===")
    for t in soup.find_all(["span", "div", "label"]):
        if t.get("id") and _clean(t.get_text(" ")):
            print(f"  {t.get('id')}  ->  {_clean(t.get_text(' '))[:60]}")
    print("\n=== link chứa /Public ===")
    for a in soup.find_all("a", href=True):
        if PUBLIC_MARK in a["href"]:
            print(f"  {_clean(a.get_text(' '))[:40]}  ->  {a['href']}")


# ----------------------- main -----------------------
def get_session():
    src = DETAIL_SH if os.path.exists(DETAIL_SH) else PAGE_SH
    url, headers, cookie = parse_curl(src)
    # bỏ các header AJAX nếu lỡ có (cần full HTML)
    for h in ("X-MicrosoftAjax", "X-Requested-With", "Content-Type", "Origin"):
        headers.pop(h, None)
    s = requests.Session()
    s.headers.update(headers)
    if cookie:
        s.headers["Cookie"] = cookie
    return s, url, src


def fetch(session, url):
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa
            last = e
            time.sleep(attempt * 2)
    raise last


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    os.makedirs(CACHE_DIR, exist_ok=True)

    session, sample_url, src = get_session()
    print(f"Dùng request từ: {os.path.basename(src)}")
    make_url = build_url_template(sample_url)

    ids = json.load(open(IDS_JSON, encoding="utf-8"))["ids"]
    if mode in ("--demo", "--dump"):
        ids = ids[:1]

    results = []
    for n, docid in enumerate(ids, 1):
        cache = os.path.join(CACHE_DIR, f"{docid}.html")
        if os.path.exists(cache) and mode not in ("--demo", "--dump"):
            html = open(cache, encoding="utf-8").read()
        else:
            html = fetch(session, make_url(docid))
            if is_login(html):
                print("\n❌ Phiên đã hết hạn / chưa đăng nhập (gặp form login).")
                print("   -> Hãy cập nhật cookie mới trong erav/detail.sh rồi chạy lại.")
                sys.exit(2)
            open(cache, "w", encoding="utf-8").write(html)

        if mode == "--dump":
            dump_structure(html)
            return

        obj = parse_detail(html)
        obj["_DocId"] = docid
        results.append(obj)

        if mode == "--demo":
            print(f"\n=== DEMO DocId={docid} ===")
            print(json.dumps(obj, ensure_ascii=False, indent=2))
            return

        if n % 25 == 0:
            print(f"  ...{n}/{len(ids)}")
        time.sleep(DELAY)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nXong: {len(results)} bản ghi -> {OUT_JSON}")


if __name__ == "__main__":
    main()
