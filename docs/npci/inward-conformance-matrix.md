# Inward (drawee) conformance matrix

Compiled 2026-10-13. Machine-checked part: `tests/modules/cts/compliance/test_npci_return_codes_conformance.py`
against `docs/npci/return_reason_codes.json`.

**Sources (updated 2026-10-14).** Primary documents were supplied and read: the **RBI/NPCI "CTS Specifications for
Continuous Clearing", Rev 3.0 (last revised 26 Mar 2025)** (the CHI file specification; the copy in
`docs/npci/source/` exists under two names, `RBI_NPCI_CHI_Specification_V_2_10...` and `RBI-NPCI-CHI-File-Specification-V3_0...`,
and they are byte-identical: the older filename is misleading, the content is Rev 3.0), the **Chennai Bankers' Clearing House CTS Procedural Guidelines v2.1** (Jul 2018), the **PPS Interface File
Specification v1.19** (Nov 2023), the NPCI Data Exchange Module (DEM) technical specification, the CTS product booklet
and the list of P2F centres (all in `docs/npci/source/`). Findings from them:

* **The return-code list is now verified against the primary text** (`docs/npci/return_reason_codes.json`: 60 of the
  spec's codes plus `00` Positive Response and `99` Deemed Accepted). The 2018 guideline numbers the RBI/government
  group 69-75; the current spec uses 70-76 (the numbering ASTRA uses). Code 92 appears only in the 2018 guideline.
* **A real defect was found and fixed:** the return-file code table (`modules/cts/rrf/models.py`) used invented codes
  (signature differs `06`, post-dated `14`, stale `15`, words/figures `16`, image quality `20` ...) and described itself as
  the only codes NGCH accepts. It is now the spec's table, pinned to the master by tests; the old tests that
  encoded the wrong codes were corrected.
* Field format: ReturnReason is a numeric string of 2-3 characters; code 99 is assigned by the clearing house when no
  response arrives (a drawee never sends it); code 88 needs a ReturnReasonComment that is non-empty and does not start
  with a digit or a space (now enforced).
* Return and presentment rules confirmed: a drawee may return an item only within its clearing length and in an
  appropriate return session; images do not travel in return clearing; presenting banks apply digital signatures with at
  least one month of certificate life left; IQA is the presenting bank's duty at capture, with an IQA indicator on each
  image; a MICR repair is signalled to the drawee by flag `010001`; paper-to-follow items carry the instrument itself.
* **Continuous clearing (Rev 3.0), the current model.** The clearing house (CCH) sets an **`ItemExpiryTime`** on every
  item. A drawee must answer before it: a positive response (`00`) or a negative one (a reason code); an item with no
  response is **Deemed Accepted (`99`)**, which the CCH assigns. A drawee may ask the CCH for a **cycle extension**
  (until the settlement cycle ends) or a **day extension** (to the next working day's settlement cycle) through an
  Extension file, and may return up to the extended expiry (example in Appx 10.7: attached 11:00, 2 h clearing length,
  2 h extension, returns allowed until 15:00). Banks can also respond, return and **recall** items online through the CCH
  web application, and the CCH publishes inward, extended and returned item reports. ASTRA already takes its deadline
  from `ItemExpiryTime` (`pxf_iet_parser.py`), as the spec requires; it does **not** implement extension requests, online
  return or recall, and the positive-response file path (`00`) is unverified because NGCH is a dev stub.
* **Not in these documents:** the "customer not at fault" list (Annexure II) comes from a bank policy reproducing
  URRBCH Annexure D, so it is still secondary. The 2018 guideline's fixed session timings (presentation 3:30-7:30 PM,
  return 12:00-2:30 PM) are superseded by the continuous-clearing model above and are not used. NPCI's separate National
  Grid circulars are not in the folder.
* **Gap found:** the PPS specification defines NPCI's CIIF file (CSV and XML: payee account, serial number, issue date
  DDMMYYYY, amount, transaction code, drawee bank name and routing number, payee name, SAN, three optional fields).
  ASTRA had no reader for it; `modules/cts/vaults/ciif.py` now parses and validates it (CSV and XML, every rule in the
  attribute table, 25 tests on the spec's own samples). It is **not yet wired** into the PPS vault upload.

This matrix is still not a certification: it has not been reviewed by someone accountable for NPCI conformance.

Status key: **DONE** implemented and tested on real images or real infrastructure · **DONE (stand-in)**
implemented, but the system it depends on is a stub or stand-in in dev · **PARTIAL** · **GAP** not built ·
**N/A (collecting side)** the obligation sits with the presenting bank, not the drawee.

## Return reason codes (Annexure D)

| Codes | Meaning | ASTRA check | Status | Evidence / note |
|---|---|---|---|---|
| 01 | Funds insufficient | `cbs_balance` | DONE (stand-in) | CBS is a dev stub |
| 02 | Exceeds arrangement | none | GAP | needs limit / arrangement data from CBS |
| 03 | Effects not cleared | none | GAP | needs uncleared-funds data from CBS |
| 04, 05 | Refer to drawer / contact bank | routed to human review | PARTIAL | no automatic emission |
| 10, 11 | Signature incomplete / illegible | signature detect + verify | PARTIAL | no distinct code; low match goes to review |
| 12 | Signature differs | `sig_verify` (embedding match) | DONE (stand-in) | specimens are self-enrolled in dev; no real genuine/impostor measurement yet |
| 13 | Signature required | `sig_detect` second look, then review | DONE | detector is non-deterministic; absent never auto-returns by default |
| 14-16 | Mandate / authority to operate | MSV module (separate) | N/A (inward CTS) | not part of this workflow |
| 17 | Alteration requires drawer's authentication | `alteration_detect` | PARTIAL | AI-based, cloud model in dev |
| 20 | Payment stopped by drawer | `stop_payment` | DONE (stand-in) | CBS stub |
| 21-25 | Attachment / court / death / lunacy / insolvency | `account_status` | PARTIAL | no distinct codes per cause |
| 30 | Post-dated | decision gate 0 | DONE | tested; implausible dates go to review (probable OCR misread) |
| 31 | Stale | decision gate 0 | DONE | 90-day limit is config; tested |
| 32 | Undated | decision gate 0 | DONE | OCR date failures go to review, never to an auto "undated" return |
| 33 | Mutilated | none | GAP | image-quality gate catches some, not a mutilation detector |
| 34 | Amount in words and figures differ | decision gate 0.5 | DONE | plus amount-vs-presented cross-check |
| 35, 40, 42 | Clearing stamp / present with document / paper not received | none | N/A (physical) | |
| 36 | Wrongly delivered / not drawn on us | `ifsc_validate`, MICR bank-code anchoring | PARTIAL | IFSC check only when the presentment IFSC is supplied |
| 37 | Present in proper zone | none | GAP | |
| 38 | Extraneous matter | `security_features` / alteration | PARTIAL | AI-based |
| 39 | Image not clear | `check_image_quality` | DONE | new; 0 of 70 genuine scans fail, 140 of 140 degraded copies caught; fails go to review |
| 41 | Item listed twice (duplicate presentment) | `duplicate_check` via cheque-leaf vault | DONE | **was silently broken until 2026-10-13**: detected by the vault but ignored by the workflow, then would have crashed; fixed and verified live |
| 50, 52 | Account closed / no such account | `account_status` | DONE (stand-in) | CBS stub |
| 51, 53, 54 | Transferred / title of account | none | GAP | |
| 55 | Account blocked | `account_status` | DONE (stand-in) | see deviation below |
| 60, 61, 63 | Crossing codes | none | GAP | crossing detection not built |
| 62, 64-68, 87 | Stamps / protective crossing / endorsement | none | N/A (collecting side), partly GAP | |
| 70-76 | RBI / Government items | none | N/A | 72 (sub-member funds) handled in the sponsor-bank module |
| 80, 81 | Bank certificate / draft lost | none | GAP | relevant to DDs |
| 82 | Bank / branch blocked | none | GAP | |
| 83 | Digital certificate validation failure | NGCH / HSM layer | DONE (stand-in) | NGCH and HSM are dev stubs |
| 84 | Connectivity failure | `ngch_file` retry, IET watchdog | DONE (stand-in) | |
| 85 | Alterations other than date | `alteration_detect` | PARTIAL | AI-based |
| 86 | Fake / forged / stolen | `fraud_score`, `security_features`, duplicate check | PARTIAL | fraud model is a synthetic stand-in |
| 88 | Other reasons | human review | DONE | |
| 92 | Bank excluded | none | N/A | |

## Other obligations

| Obligation | ASTRA | Status | Note |
|---|---|---|---|
| Inward Exchange Time (IET) window; missed IET = deemed approval | `IETWatchdogWorkflow`, T-30s emergency file | DONE (stand-in) | verified live: a 40 s deadline fired `EMERGENCY_FILED`. **Open defect:** after an emergency filing the main pipeline still queues a human review |
| Exactly-once NGCH filing | `ngch_filer` idempotency | DONE (stand-in) | NGCH is a dev stub |
| NPCI PPS interface (CIIF file, positive pay) | `modules/cts/vaults/ciif.py` | PARTIAL | parser and validator done and tested on the spec samples; not wired into the vault upload; file-name convention, reject-reason and response files not implemented |
| Respond before `ItemExpiryTime`; no response = deemed accepted (`99`) | `IETWatchdogWorkflow` + `pxf_iet_parser` | DONE (stand-in) | deadline taken per item from the file; verified live with a dev NGCH stub; real NGCH timing untested |
| Request cycle / day extension (Extension file) | none | GAP | needed when a decision cannot be made before expiry |
| Online return and recall via the CCH web application | none | GAP | manual route exists at the clearing house; no ASTRA integration |
| Positive response (`00`) for on-realisation items | `file_to_ngch` CONFIRM path | UNVERIFIED | no evidence the real file carries `00`; NGCH is a stub |
| Preserve images of government cheques for 10 years, separate from clearing images | MinIO WORM tiers (10-year cold tier) | PARTIAL | retention tier exists; no government-cheque flag or separate store |
| Drawee may return government / other cheques as 'present with document' (40) to see the paper | human review path | PARTIAL | no automatic emission; the physical-cheque request workflow is not built |
| Single National Grid (one grid since 13 Oct 2023) | grid-agnostic design | DONE | no per-grid assumptions in the code |
| Digital-signature validation of presenting file | NGCH / HSM layer | DONE (stand-in) | |
| Physical cheque request (NI Act s.64(2)) | none | GAP | no workflow to demand the instrument |
| CTS-2010 image standards (grey 100 dpi; B/W 200 dpi) | `check_image_quality` | PARTIAL | grey images only; no TIFF B/W or UV image handling |
| CTS-2010 mandatory security features | `check_security_features` | PARTIAL | AI-based on the image; UV, watermark and void pantograph are not visible in a grey image |
| MICR band legibility (E13B) | OCR + sort-code anchoring, number cross-check, branch master | DONE | wrong digits inside the window need the branch master / presented number |
| Return charges: customer at fault or not | `NON_CUSTOMER_FAULT_CODES` | DONE, with a deviation | see below |

## Deviation needing a compliance decision

`NON_CUSTOMER_FAULT_CODES` equals Annexure II **plus** codes 30, 31, 32 and 55. The code comments call this "by
convention: the collecting bank should have rejected it at intake" and older tests cite four banks'
customer-compensation policies. Annexure II does not list them, so on the annexure alone the depositor is at
fault and return charges would apply. The deviation is pinned in the conformance test so it can change only
deliberately. **Decision needed from a compliance officer, not from engineering.**

## Counts (of the 64 annexure codes, the non-physical, drawee-relevant ones)

DONE or DONE (stand-in): 01, 12, 13, 20, 30, 31, 32, 34, 39, 41, 50, 52, 55, 83, 84, 88.
PARTIAL: 04, 05, 10, 11, 17, 21-25, 36, 38, 85, 86.
GAP: 02, 03, 33, 37, 51, 53, 54, 60, 61, 63, 80, 81, 82, plus the return-session calendar and the physical-cheque request.
