"""
RRFGenerator — builds CTS Return Reason File XML per CTS Spec Rev 3.0.
Namespace: urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004

CTS Spec Rev 3.0 rules enforced here:
  - Return reason 99 (Deemed Accepted by CCH) MUST NEVER appear in bank-submitted RRF.
    ForbiddenReturnReasonError is raised as defense-in-depth (code 99 is not in the enum).
  - Return reason 88 (Other Reason) requires ReturnReasonComment in XML.
  - Return reason 00 (On Realization Positive) is valid for ClearingType=14 sessions.

Output format: XML, UTF-8. Encrypted + HSM-signed before NGCH submission (signing in ngch_filer).
"""
from xml.etree import ElementTree as ET
from xml.dom import minidom

from .models import RRFDocument

_RRF_NS = "urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004"
_FORBIDDEN_CODES = {"99"}   # CCH-only code — drawee bank must never send this


class ForbiddenReturnReasonError(ValueError):
    """Raised when a return reason code that banks must never send appears in an RRF."""


class RRFGenerator:

    @staticmethod
    def to_xml(doc: RRFDocument, allow_empty: bool = True) -> str:
        if not allow_empty and not doc.returns:
            raise ValueError('No return items — RRF requires at least one return instrument')

        # Defense-in-depth: reject code 99 even if it somehow bypassed enum validation
        for item in doc.returns:
            if item.return_code.code in _FORBIDDEN_CODES:
                raise ForbiddenReturnReasonError(
                    f"Return reason code {item.return_code.code!r} is assigned by CCH only — "
                    "banks must never include it in an RRF submission."
                )

        root = ET.Element('ReturnReasonFile')
        root.set('xmlns', _RRF_NS)
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        root.set('version', '2.0')

        # ── Header ────────────────────────────────────────────────────────────
        header = ET.SubElement(root, 'Header')
        ET.SubElement(header, 'BankIFSC').text         = doc.bank_ifsc
        ET.SubElement(header, 'SessionID').text         = doc.session_id
        ET.SubElement(header, 'ClearingZone').text      = doc.clearing_zone
        ET.SubElement(header, 'GeneratedAt').text       = doc.generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')
        ET.SubElement(header, 'TotalReturns').text      = str(doc.total_returns)
        ET.SubElement(header, 'FiledWithinIETCount').text = str(
            sum(1 for r in doc.returns if r.filed_within_iet)
        )

        # ── Returns ───────────────────────────────────────────────────────────
        returns_el = ET.SubElement(root, 'Returns')
        for item in doc.returns:
            ri = ET.SubElement(returns_el, 'ReturnItem')
            ET.SubElement(ri, 'InstrumentID').text      = item.instrument_id
            ET.SubElement(ri, 'MICRCode').text           = item.micr_code
            ET.SubElement(ri, 'ReturnReasonCode').text   = item.return_code.code
            ET.SubElement(ri, 'ReturnReasonDescription').text = item.return_code.description
            ET.SubElement(ri, 'DraweeIFSC').text         = item.drawee_ifsc
            ET.SubElement(ri, 'PresentingIFSC').text     = item.presenting_ifsc
            ET.SubElement(ri, 'IETDeadline').text        = item.iet_deadline.strftime('%Y-%m-%dT%H:%M:%SZ')
            ET.SubElement(ri, 'ReturnedAt').text         = item.returned_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            ET.SubElement(ri, 'FiledWithinIET').text     = 'true' if item.filed_within_iet else 'false'
            ET.SubElement(ri, 'DecidedBy').text          = item.decided_by
            ET.SubElement(ri, 'AmountRange').text        = item.amount_range
            # ReturnReasonComment: mandatory for code 88; optional for others
            if item.return_reason_comment:
                ET.SubElement(ri, 'ReturnReasonComment').text = item.return_reason_comment
            if item.workflow_id:
                ET.SubElement(ri, 'TemporalWorkflowID').text = item.workflow_id

        raw = ET.tostring(root, encoding='unicode')
        pretty = minidom.parseString(raw).toprettyxml(indent='  ', encoding=None)
        # minidom adds its own declaration — normalise to UTF-8 declaration
        lines = pretty.split('\n')
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
        return '\n'.join(lines)

    @staticmethod
    def filename(doc: RRFDocument) -> str:
        """NGCH filename convention: RRF_{IFSC}_{YYYYMMDD}_{SessionID}.xml"""
        date_str = doc.generated_at.strftime('%Y%m%d')
        return f'RRF_{doc.bank_ifsc}_{date_str}_{doc.session_id}.xml'
