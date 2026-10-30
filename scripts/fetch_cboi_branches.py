"""Download the Central Bank of India branch list from the bank's public branch locator
(https://centralbank.bank.in/branch_locators/): states -> districts -> branches, sequential and slow on purpose.

Usage: python scripts/fetch_cboi_branches.py [out.csv]
Writes every branch (code, name, IFSC, MICR, region, zone, district, state, address, PIN, classification, phone, mobile, email).
"""
import csv
import html
import re
import sys
import time

import httpx

URL = "https://centralbank.bank.in/branch_locators/load-cs.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (ASTRA demo data fetch)"}
DELAY = 0.3
COLUMNS = ["BRANCH_CODE", "BRANCH_NAME", "IFSC_CODE", "MICR_CODE", "REGION", "ZONE", "DIST_NAME", "STATE_UNION_TERRITORY",
           "ADDRESS", "PIN_CODE", "CLASSIFICATION", "LAND_LINE_NO", "MOBILE_NO", "EMAILS"]


def options(markup: str) -> list[str]:
    return [html.unescape(v) for v in re.findall(r'<option value="([^"]+)"', markup)]


def rows(markup: str) -> list[list[str]]:
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", markup, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td>(.*?)</td>", tr, re.S)]
        if len(cells) == len(COLUMNS):
            out.append(cells)
    return out


def post(client: httpx.Client, **data) -> str:
    for attempt in range(4):
        try:
            r = client.post(URL, data=data, timeout=60)
            r.raise_for_status()
            time.sleep(DELAY)
            return r.text
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gave up on {data}")


def main(path: str) -> None:
    seen: dict[str, list[str]] = {}
    with httpx.Client(headers=HEADERS) as c:
        states = options(post(c, action="getState"))
        print(len(states), "states", flush=True)
        for st in states:
            for dist in options(post(c, action="getDist", state_id=st)):
                for r in rows(post(c, action="getalldata", state_id=st, district=dist)):
                    seen[r[0]] = r
            print(f"{st}: total so far {len(seen)}", flush=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(sorted(seen.values(), key=lambda r: (r[7], r[6], r[1])))
    print("branches:", len(seen), "->", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cboi_branches.csv")
