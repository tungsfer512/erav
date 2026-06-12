#!/usr/bin/env python3
"""
Tải tất cả các trang (1..234) của RadGrid trên ERAVCertificatorView.aspx
và lưu mỗi trang thành 1 file HTML trong thư mục ./html

Trang này là ASP.NET WebForms + Telerik RadGrid (RadAjaxPanel):
  - Phân trang bằng AJAX postback; __VIEWSTATE / __EVENTVALIDATION đổi mỗi request
    => bắt buộc tải TUẦN TỰ, lấy token mới từ response trước.
  - Dùng dropdown "chọn trang" (ddlChoiceIndexOfPage) để nhảy tới trang bất kỳ.
  - Response là định dạng MS-Ajax delta (length|type|id|content|...). Ta parse:
      * segment updatePanel  -> phần HTML của lưới (lưu ra file)
      * segment hiddenField  -> __VIEWSTATE / __EVENTVALIDATION / ... (token mới)

Cấu hình lấy nguyên từ page.sh (headers, cookie, body) cho trùng với trình duyệt.
"""

import os
import re
import sys
import time
import shlex
from urllib.parse import parse_qsl, urlencode

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_SH = os.path.join(HERE, "page.sh")
OUT_DIR = os.path.join(HERE, "html")
RAW_DIR = os.path.join(HERE, "html", "raw")   # lưu nguyên gói delta thô
SAVE_RAW = True

FIRST_PAGE = 1
LAST_PAGE = 234
DELAY = 0.7          # giây nghỉ giữa các request
TIMEOUT = 60
MAX_RETRY = 4

DDL = "ctl00$cplhContainer$ddlChoiceIndexOfPage"            # dropdown chọn trang
PANEL = "ctl00$cplhContainer$ctl00$cplhContainer$radAjaxPanelViewPanel"
TOKEN_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR",
                "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED", "__LASTFOCUS")


def parse_curl(path):
    """Đọc file page.sh (lệnh curl) -> (url, headers, cookie, body_pairs)."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().replace("\\\n", " ")
    tokens = shlex.split(text)

    url = headers = cookie = body = None
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
        elif t in ("--data-raw", "--data", "-d", "--data-binary"):
            body = tokens[i + 1]
            i += 2
        else:
            if t.startswith("http"):
                url = t
            i += 1
    return url, headers, cookie, parse_qsl(body, keep_blank_values=True)


def parse_delta(text):
    """
    Parse MS-Ajax delta: chuỗi các bản ghi `len|type|id|content|`.
    Trả về (updatepanels: {id: html}, hidden: {name: value}).
    """
    updatepanels = {}
    hidden = {}
    i = 0
    n = len(text)
    while i < n:
        j = text.find("|", i)
        if j < 0:
            break
        length_str = text[i:j]
        if not length_str.isdigit():
            break
        length = int(length_str)
        k = text.find("|", j + 1)            # sau type
        seg_type = text[j + 1:k]
        m = text.find("|", k + 1)            # sau id
        seg_id = text[k + 1:m]
        content = text[m + 1:m + 1 + length]
        if seg_type == "updatePanel":
            updatepanels[seg_id] = content
        elif seg_type == "hiddenField":
            hidden[seg_id] = content
        i = m + 1 + length + 1               # bỏ qua dấu '|' kết thúc bản ghi
    return updatepanels, hidden


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if SAVE_RAW:
        os.makedirs(RAW_DIR, exist_ok=True)
    url, headers, cookie, body_pairs = parse_curl(PAGE_SH)

    data = dict(body_pairs)
    session = requests.Session()
    session.headers.update(headers)
    if cookie:
        session.headers["Cookie"] = cookie

    def fetch(target):
        d = dict(data)
        d["ctl00$RadScriptManager1"] = PANEL + "|" + DDL
        d["__EVENTTARGET"] = DDL
        d["__EVENTARGUMENT"] = ""
        d[DDL] = str(target)
        body = urlencode(d)
        last = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = session.post(url, data=body, timeout=TIMEOUT)
                r.raise_for_status()
                return r.text
            except Exception as e:  # noqa
                last = e
                wait = attempt * 2
                print(f"   ! lỗi (lần {attempt}/{MAX_RETRY}): {e} -> chờ {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
        raise last

    ok = 0
    for page in range(FIRST_PAGE, LAST_PAGE + 1):
        raw = fetch(page)

        if SAVE_RAW:
            with open(os.path.join(RAW_DIR, f"page_{page:03d}.txt"),
                      "w", encoding="utf-8") as f:
                f.write(raw)

        panels, hidden = parse_delta(raw)

        # cập nhật token cho request kế tiếp
        for name in TOKEN_FIELDS:
            if name in hidden:
                data[name] = hidden[name]

        grid_html = panels.get("ctl00_cplhContainer_ctl00_cplhContainer_radAjaxPanelViewPanel")

        if grid_html and "rgMasterTable" in grid_html:
            out = os.path.join(OUT_DIR, f"page_{page:03d}.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(
                    "<!DOCTYPE html>\n<html lang=\"vi\"><head>"
                    "<meta charset=\"utf-8\">"
                    f"<title>ERAV - trang {page}</title></head><body>\n"
                    + grid_html +
                    "\n</body></html>\n"
                )
            rows = grid_html.count('class="rgRow"') + grid_html.count('class="rgAltRow"')
            ok += 1
            print(f"[{page:3d}/{LAST_PAGE}] OK  ~{rows} dòng  -> {os.path.basename(out)}")
        else:
            out = os.path.join(OUT_DIR, f"page_{page:03d}.DEBUG.txt")
            with open(out, "w", encoding="utf-8") as f:
                f.write(raw)
            print(f"[{page:3d}/{LAST_PAGE}] ⚠ không thấy lưới -> {os.path.basename(out)}",
                  file=sys.stderr)

        time.sleep(DELAY)

    print(f"\nXong: {ok}/{LAST_PAGE - FIRST_PAGE + 1} trang đã lưu vào {OUT_DIR}")


if __name__ == "__main__":
    main()
