# Inward (drawee) conformance matrix

Compiled 2026-10-13. Machine-checked part: `tests/modules/cts/compliance/test_npci_return_codes_conformance.py`
against `docs/npci/return_reason_codes.json`.

**Source limits (read first).** The primary RBI/NPCI procedural guidelines could not be retrieved in this
session (RBI's host serves a human-verification page; NPCI's pages are script-rendered). The master of return
reason codes is the clearing-house annexure (Annexure D, Uniform Regulations and Rules for Bankers' Clearing
Houses) as reproduced in a bank's published collection policy: a secondary source quoting the authoritative
annexure. Statements about timing windows, digital-certificate handling and the physical-cheque request come
from search-result excerpts of the RBI guidelines and the NI Act s.64(2), not from the full text. **Before any
certification claim: a person with access to the current NPCI procedural guidelines must verify this matrix
against them.**

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
| Return only within clearing length / return session | not modelled | GAP | session calendar not implemented |
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
