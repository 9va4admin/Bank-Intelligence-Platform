import pytest

from modules.cts.fraud_training.io import ContractViolation, load_labelled_csv

HEADER = "timestamp,is_fraud,amount,ocr_confidence,alteration_flag,signature_match_score,amount_to_balance_ratio,pps_found,amount_vs_account_median,payee_seen_before,cheques_last_24h,days_since_account_opened"


def _write(tmp_path, rows):
    p = tmp_path / "d.csv"
    p.write_text("\n".join([HEADER] + rows), encoding="utf-8")
    return str(p)


def test_loads_features_labels_and_timestamps(tmp_path):
    p = _write(tmp_path, ["1700000000,0,5000,0.9,0,0.8,0.1,1,1.2,1,2,400", "1700000100,1,90000,0.6,1,0.4,0.9,0,8.0,0,9,12"])
    X, y, ts = load_labelled_csv(p)
    assert list(y) == [0, 1] and list(ts) == [1700000000, 1700000100]
    assert X["amount"] == [5000.0, 90000.0]


def test_empty_cell_is_missing_not_zero(tmp_path):
    p = _write(tmp_path, ["1700000000,0,5000,0.9,0,,0.1,1,,,2,400"])
    X, _, _ = load_labelled_csv(p)
    assert X["signature_match_score"] == [None] and X["payee_seen_before"] == [None]


def test_non_binary_label_is_rejected(tmp_path):
    with pytest.raises(ContractViolation):
        load_labelled_csv(_write(tmp_path, ["1700000000,2,5000,0.9,0,0.8,0.1,1,1.2,1,2,400"]))


def test_missing_required_column_is_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,amount\n1,2\n", encoding="utf-8")
    with pytest.raises(ContractViolation):
        load_labelled_csv(str(p))


def test_raw_account_numbers_are_refused_by_the_contract(tmp_path):
    p = tmp_path / "pii.csv"
    p.write_text(HEADER + ",account_number\n1700000000,0,5000,0.9,0,0.8,0.1,1,1.2,1,2,400,123456789012\n", encoding="utf-8")
    with pytest.raises(ContractViolation):
        load_labelled_csv(str(p))
