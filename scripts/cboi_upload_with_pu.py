"""Add a 'PU ID' column to the Central Bank of India upload file: each branch goes to the processing unit of its
NGCH grid zone, chosen by state. The state->zone table is a DEMO assumption - confirm it against the bank's own grid list."""
import csv, sys

ZONE_OF_STATE = {
    "DELHI": ["Delhi", "Haryana", "Punjab", "Chandigarh(Ut)", "Himachal Pradesh", "Jammu&Kashmir(Ut)", "Jammu & Kashmir", "Uttarakhand",
              "Uttar Pradesh", "Rajasthan", "Ladakh", "Ladakh (Ut)", "Nct Of Delhi(Ut)", "Uttrakhand"],
    "MUMBAI": ["Maharashtra", "Goa", "Madhya Pradesh", "Chhattisgarh", "Dadra&Nagarhaveli(Ut)", "Daman&Diu(Ut)",
               "Union Territory Of Dadra/Nagar Haveli/Diu/Daman"],
    "AHMEDABAD": ["Gujarat"],
    "KOLKATA": ["West Bengal", "Bihar", "Jharkhand", "Odisha", "Orissa", "Assam", "Arunachalpradesh", "Manipur", "Meghalaya", "Mizoram",
                "Nagaland", "Tripura", "Sikkim", "Andaman&Nicobar(Ut)"],
    "CHENNAI": ["Tamil Nadu", "Kerala", "Karnataka", "Pondicherry(Ut)", "Puducherry", "Lakshadweep(Ut)"],
    "HYDERABAD": ["Telangana", "Andhra Pradesh"],
}
PU_OF_ZONE = {"MUMBAI": "CBIN-PU-MUMBAI", "DELHI": "CBIN-PU-DELHI", "KOLKATA": "CBIN-PU-KOLKATA", "HYDERABAD": "CBIN-PU-HYDERABAD",
              "AHMEDABAD": "CBIN-PU-AHMEDABAD", "CHENNAI": "KBL-PU-01"}
PU_OF_STATE = {s.lower(): PU_OF_ZONE[z] for z, states in ZONE_OF_STATE.items() for s in states}

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
unmapped = sorted({r["State"] for r in rows if r["State"].lower() not in PU_OF_STATE})
print("unmapped states:", unmapped)
with open(dst, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(list(rows[0].keys()) + ["PU ID"])
    for r in rows:
        w.writerow(list(r.values()) + [PU_OF_STATE.get(r["State"].lower(), "")])
print(len(rows), "rows ->", dst)
