"""
CTS-2010 Compliance Certificate XML Exporter.

Generates a structured XML certificate per batch/lot for regulatory record-keeping
and optional submission to NPCI clearing infrastructure.
Filename: CTS2010_CERT_{IFSC}_{YYYYMMDD}_{SessionID}_{LotSuffix}.xml
"""
from __future__ import annotations

import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET
import re

from modules.cts.compliance.cts2010 import CTS2010Standard
from modules.cts.compliance.models import BatchComplianceCertificate


def _lot_suffix(batch_id: str) -> str:
    match = re.search(r'_(\d{2})$', batch_id)
    return f'LOT{match.group(1)}' if match else 'LOT01'


class CertificateExporter:
    @staticmethod
    def to_xml(cert: BatchComplianceCertificate) -> str:
        root = ET.Element('CTS2010ComplianceCertificate')
        root.set('xmlns', 'urn:in:rbi:cts:2010:compliance')
        root.set('version', '1.0')

        # Header
        hdr = ET.SubElement(root, 'Header')
        ET.SubElement(hdr, 'BankIFSC').text          = cert.bank_ifsc
        ET.SubElement(hdr, 'SessionID').text          = cert.session_id
        ET.SubElement(hdr, 'BatchID').text            = cert.batch_id
        ET.SubElement(hdr, 'IssuedAt').text           = cert.issued_at.isoformat()
        ET.SubElement(hdr, 'OverallResult').text       = cert.overall_result.value
        ET.SubElement(hdr, 'TotalInstruments').text   = str(cert.total_instruments)
        ET.SubElement(hdr, 'PassedCount').text        = str(cert.passed_count)
        ET.SubElement(hdr, 'FailedCount').text        = str(cert.failed_count)
        ET.SubElement(hdr, 'PassRate').text           = f'{cert.pass_rate:.2f}'

        # Standard reference
        std = ET.SubElement(root, 'CTS2010StandardReference')
        ET.SubElement(std, 'MinDPI').text            = str(CTS2010Standard.MIN_DPI)
        ET.SubElement(std, 'MinColourDepth').text    = str(CTS2010Standard.MIN_COLOUR_DEPTH)
        ET.SubElement(std, 'MaxFileSizeKB').text     = str(CTS2010Standard.MAX_FILE_SIZE_KB)
        ET.SubElement(std, 'MinIQAScore').text       = str(CTS2010Standard.MIN_IQA_SCORE)
        ET.SubElement(std, 'MICRBandMinScore').text  = str(CTS2010Standard.MICR_BAND_MIN_SCORE)

        # Instruments
        instruments_el = ET.SubElement(root, 'Instruments')
        for item in cert.instruments:
            el = ET.SubElement(instruments_el, 'Instrument')
            ET.SubElement(el, 'InstrumentID').text   = item.instrument_id
            ET.SubElement(el, 'ChequeNumber').text   = item.cheque_number
            ET.SubElement(el, 'LotNumber').text      = item.lot_number
            ET.SubElement(el, 'Result').text         = item.result.value

            front = ET.SubElement(el, 'FrontImage')
            ET.SubElement(front, 'DPI').text          = str(item.front_dpi)
            ET.SubElement(front, 'ColourDepth').text  = str(item.front_colour_depth)
            ET.SubElement(front, 'FileSizeKB').text   = f'{item.front_file_size_kb:.2f}'
            ET.SubElement(front, 'IQAScore').text     = f'{item.front_iqa_score:.4f}'

            rear = ET.SubElement(el, 'RearImage')
            ET.SubElement(rear, 'DPI').text           = str(item.rear_dpi)
            ET.SubElement(rear, 'ColourDepth').text   = str(item.rear_colour_depth)
            ET.SubElement(rear, 'FileSizeKB').text    = f'{item.rear_file_size_kb:.2f}'
            ET.SubElement(rear, 'IQAScore').text      = f'{item.rear_iqa_score:.4f}'

            ET.SubElement(el, 'MICRBandScore').text  = f'{item.micr_band_score:.4f}'

            if item.failure_reasons:
                fails = ET.SubElement(el, 'FailureReasons')
                for reason in item.failure_reasons:
                    ET.SubElement(fails, 'Reason').text = reason

        raw = ET.tostring(root, encoding='unicode', xml_declaration=False)
        pretty = minidom.parseString(raw).toprettyxml(indent='  ', encoding=None)
        if not pretty.startswith('<?xml'):
            pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty
        return pretty

    @staticmethod
    def filename(cert: BatchComplianceCertificate) -> str:
        date_str = cert.issued_at.strftime('%Y%m%d')
        suffix   = _lot_suffix(cert.batch_id)
        return f'CTS2010_CERT_{cert.bank_ifsc}_{date_str}_{cert.session_id}_{suffix}.xml'
