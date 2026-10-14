"""Database lot assignment (cts.lots). Shared by the API and the outward-scan workflow activities."""
from typing import Tuple


async def ensure_open_lot(
    conn,
    bank_id: str,
    branch_id: str,
    session_id: str,
    clearing_date,
    max_instruments: int = 25,
) -> Tuple[str, int]:
    """Find or create the OPEN scanning lot for (branch, date), count one more instrument in it, and return
    (lot_id, count). A lot that reaches max_instruments is sealed and the next one opened."""
    row = await conn.fetchrow(
        "SELECT lot_id, instrument_count, max_instruments "
        "FROM cts.lots "
        "WHERE branch_id = $1 AND clearing_date = $2 AND status = 'OPEN'",
        branch_id, clearing_date,
    )

    if row is None:
        seq_row = await conn.fetchrow(
            "SELECT COALESCE(MAX(sequence_number), 0) AS max_seq "
            "FROM cts.lots WHERE branch_id = $1 AND clearing_date = $2",
            branch_id, clearing_date,
        )
        seq = (seq_row["max_seq"] or 0) + 1
        date_str = clearing_date.strftime("%Y%m%d") if hasattr(clearing_date, "strftime") else str(clearing_date).replace("-", "")
        lot_id = f"LOT-{branch_id}-{date_str}-{seq:04d}"
        await conn.execute(
            "INSERT INTO cts.lots "
            "(lot_id, bank_id, branch_id, session_id, clearing_date, sequence_number, "
            " status, instrument_count, max_instruments) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'OPEN', 1, $7)",
            lot_id, bank_id, branch_id, session_id, clearing_date, seq, max_instruments,
        )
        return lot_id, 1

    lot_id = row["lot_id"]
    new_count = row["instrument_count"] + 1

    if new_count >= row["max_instruments"]:
        await conn.execute(
            "UPDATE cts.lots SET status='SEALED', instrument_count=$1, sealed_at=NOW() WHERE lot_id=$2",
            new_count, lot_id,
        )
        return await ensure_open_lot(conn, bank_id, branch_id, session_id, clearing_date, max_instruments)

    await conn.execute("UPDATE cts.lots SET instrument_count=$1 WHERE lot_id=$2", new_count, lot_id)
    return lot_id, new_count
