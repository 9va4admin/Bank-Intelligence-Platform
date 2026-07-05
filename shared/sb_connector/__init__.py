"""shared/sb_connector — Agency → Sponsor Bank adapter layer.

Factory usage:
    from shared.sb_connector.base import get_connector_for_type
    connector = get_connector_for_type("SFTP_GENERIC", agency_id, sb_bank_id)
    result = await connector.submit_lot(lot_path, instrument_count, session_id)
"""
