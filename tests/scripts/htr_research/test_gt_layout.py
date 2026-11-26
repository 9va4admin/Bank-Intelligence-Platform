"""The tab-separated layout of the other IIIT-Indic-HW-Words sets (Gujarati and the rest): `<split>/<split>_gt.txt` rows `images/N.jpg<TAB>word`."""
import pytest

from htr_research.dataset import LabelError, TabGtDataset, validate_gt_layout


def make(root, rows_by_split, create_images=True):
    for split, rows in rows_by_split.items():
        folder = root / split
        (folder / "images").mkdir(parents=True)
        (folder / f"{split}_gt.txt").write_text("".join(f"images/{n}.jpg\t{w}\n" for n, w in rows), encoding="utf-8")
        if create_images:
            for n, _ in rows:
                (folder / "images" / f"{n}.jpg").write_bytes(b"x")
    return root


ROWS = {"train": [(1, "નમસ્તે"), (2, "ભારત"), (3, "બેંક")], "val": [(1, "ભારત")], "test": [(1, "ભારત"), (2, "શહેર")]}


def test_reads_paths_and_words(tmp_path):
    root = make(tmp_path, ROWS)
    ds = TabGtDataset(root, "train")
    assert len(ds) == 3
    assert ds.samples[0].text == "નમસ્તે"
    assert ds.samples[0].path == root / "train" / "images" / "1.jpg"


def test_word_may_contain_spaces_but_not_tabs_split_wrongly(tmp_path):
    root = make(tmp_path, {"train": [(1, "બે શબ્દ")], "val": [], "test": [(1, "બે શબ્દ")]})
    assert TabGtDataset(root, "train").samples[0].text == "બે શબ્દ"


def test_missing_split_raises(tmp_path):
    with pytest.raises(LabelError):
        TabGtDataset(tmp_path, "train")


def test_row_without_a_word_raises(tmp_path):
    root = make(tmp_path, ROWS)
    (root / "train" / "train_gt.txt").write_text("images/1.jpg\t\n", encoding="utf-8")
    with pytest.raises(LabelError):
        TabGtDataset(root, "train")


def test_validate_reports_counts_missing_and_unseen_share(tmp_path):
    root = make(tmp_path, ROWS)
    (root / "test" / "images" / "2.jpg").unlink()
    report = validate_gt_layout(root, expected_counts={"train": 3, "val": 1, "test": 2})
    assert report.counts == {"train": 3, "val": 1, "test": 2}
    assert report.counts_match is True
    assert report.missing["test"] == ["test/images/2.jpg"]
    assert report.test_unseen_word_share == pytest.approx(0.5)   # શહેર is not in training; ભારત is
    assert report.ok is False                                    # an image is missing


def test_validate_flags_count_mismatch(tmp_path):
    root = make(tmp_path, ROWS)
    assert validate_gt_layout(root, expected_counts={"train": 4, "val": 1, "test": 2}).counts_match is False


def test_writers_are_reported_as_unknown(tmp_path):
    report = validate_gt_layout(make(tmp_path, ROWS))
    assert report.writers_known is False
