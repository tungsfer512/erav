#!/usr/bin/env python3
"""
Trích toàn bộ Id (trong "_clientKeyValues") từ các file thô html/raw/page_XXX.txt
và lưu vào ids.json.

Cấu trúc mỗi file có 1 khối, ví dụ:
  "_clientKeyValues":{"0":{"Id":"65"},"1":{"Id":"40"}, ... ,"9":{"Id":"32"}}
"""

import os
import re
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "html", "raw")
OUT_JSON = os.path.join(HERE, "ids.json")

# bắt nguyên khối _clientKeyValues (gồm các cặp "idx":{"Id":"..."})
BLOCK = re.compile(
    r'"_clientKeyValues":(\{(?:"\d+":\{"Id":"[^"]*"\},?)*\})'
)


def main():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "page_*.txt")))
    by_page = {}
    all_ids = []

    for fp in files:
        page = re.search(r"page_(\d+)\.txt$", fp).group(1)
        text = open(fp, encoding="utf-8").read()
        m = BLOCK.search(text)
        if not m:
            print(f"[trang {page}] ⚠ không tìm thấy _clientKeyValues")
            by_page[page] = []
            continue
        # parse JSON khối -> {"0":{"Id":"65"},...} ; lấy theo thứ tự index
        obj = json.loads(m.group(1))
        ids = [obj[k]["Id"] for k in sorted(obj, key=int)]
        by_page[page] = ids
        all_ids.extend(ids)

    result = {
        "total": len(all_ids),
        "pages": len(files),
        "ids": all_ids,          # danh sách phẳng theo đúng thứ tự trang 1..234
        "by_page": by_page,      # tra cứu theo từng trang
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Xong: {len(all_ids)} Id từ {len(files)} trang -> {OUT_JSON}")
    # cảnh báo trùng (nếu có)
    dup = len(all_ids) - len(set(all_ids))
    if dup:
        print(f"  ⚠ có {dup} Id trùng nhau")


if __name__ == "__main__":
    main()
