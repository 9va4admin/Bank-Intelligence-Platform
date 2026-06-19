"""
RRFGenerator — builds CTS Return Reason File XML per NGCH specification.
Output format: XML, encrypted + HSM-signed before NGCH submission (signing done by ngch_filer).
"""
from xml.etree import ElementTree as ET
from xml.dom import minidom

from .models import RRFDocument


class RRFGenerator:

    @staticmethod
    def to_xml(doc: RRFDocument, allow_empty: bool = True) -> str:
        if not allow_empty and not doc.returns:
            raise ValueError('No return items — RRF requires at least one return instrument')

        root = ET.Element('ReturnReasonFile')
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
