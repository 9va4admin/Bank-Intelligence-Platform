"""Loading and checking IIIT-Indic-HW-Words style data: label rows are `<path>, <vocab id>`, `vocab.txt` holds one word per line (line number = id), images are word crops."""
import pytest
from PIL import Image

from htr_research.dataset import (
    Charset, LabelError, WordDataset, build_charset, load_vocab, parse_label_line, validate,
)

VOCAB = ["ರಾಜು", "ಪಂಡಿತ್", "abc", "ab"]


def make_root(tmp_path, labels=None, make_images=True, vocab=VOCAB):
    (tmp_path / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")
    labels = labels if labels is not None else {"train": [(1, 0), (2, 1), (3, 2)], "val": [(1, 3)], "test": [(1, 0), (2, 3)]}
    for split, rows in labels.items():
        (tmp_path / split).mkdir()
        for n, _ in rows:
            if make_images:
                Image.new("L", (40 + n, 16), 255).save(tmp_path / split / f"{n}.jpg")
        (tmp_path / f"{split}.txt").write_text("".join(f"{split}/{n}.jpg, {vid}\n" for n, vid in rows), encoding="utf-8")
    return tmp_path


def test_a_label_row_gives_the_image_path_and_the_vocabulary_id():
    assert parse_label_line("train/1.jpg, 5172") == ("train/1.jpg", 5172)
    assert parse_label_line("  val/22.jpg ,3  \n") == ("val/22.jpg", 3)
    for bad in ("", "train/1.jpg", "train/1.jpg, x", ", 5", "a, b, c"):
        with pytest.raises(LabelError):
            parse_label_line(bad)


def test_the_vocabulary_maps_a_line_number_to_a_word_and_refuses_blank_lines(tmp_path):
    p = tmp_path / "vocab.txt"
    p.write_text("ರಾಜು\nabc\n", encoding="utf-8")
    assert load_vocab(p) == ["ರಾಜು", "abc"]
    p.write_text("one\n\ntwo\n", encoding="utf-8")
    with pytest.raises(LabelError):
        load_vocab(p)


def test_a_dataset_gives_each_image_path_with_its_word_and_knows_its_size(tmp_path):
    root = make_root(tmp_path)
    ds = WordDataset(root, "train")
    assert len(ds) == 3 and ds.samples[0].text == "ರಾಜು" and ds.samples[2].text == "abc"
    assert ds.samples[1].path == root / "train" / "2.jpg"
    assert len(WordDataset(root, "val")) == 1 and len(WordDataset(root, "test")) == 2
    with pytest.raises(LabelError):
        WordDataset(root, "nope")


def test_a_label_that_points_outside_the_vocabulary_is_an_error_not_a_silent_wrong_word(tmp_path):
    root = make_root(tmp_path, labels={"train": [(1, 99)]})
    with pytest.raises(LabelError):
        WordDataset(root, "train")


def test_validation_reports_counts_missing_images_charset_size_and_unseen_words(tmp_path):
    root = make_root(tmp_path)
    (root / "train" / "2.jpg").unlink()                                              # one image is missing
    report = validate(root, expected_counts={"train": 3, "val": 1, "test": 2})
    assert report.counts == {"train": 3, "val": 1, "test": 2} and report.counts_match is True
    assert report.missing == {"train": ["train/2.jpg"], "val": [], "test": []}
    assert report.charset_size == len(set("".join(VOCAB))) and report.vocab_size == 4
    assert report.ok is False                                                         # a missing image makes the data not ok
    assert report.test_unseen_word_share == pytest.approx(0.5)                        # of 2 test images, the word of one (id 3) never appears in the training labels
    mismatch = validate(make_root_alt(tmp_path), expected_counts={"train": 9, "val": 1, "test": 2})
    assert mismatch.counts_match is False


def make_root_alt(tmp_path):
    alt = tmp_path / "alt"
    alt.mkdir()
    return make_root(alt)


def test_the_charset_reserves_zero_for_the_blank_and_round_trips_words_in_any_script():
    cs = build_charset(VOCAB)
    assert isinstance(cs, Charset) and cs.size == len(set("".join(VOCAB))) + 1
    for word in VOCAB:
        ids = cs.encode(word)
        assert 0 not in ids and cs.decode(ids) == word
    assert cs.decode([0, 0]) == ""
    with pytest.raises(LabelError):
        cs.encode("ಅ")                                                                # a character the data never uses


def test_validating_a_folder_without_labels_or_without_a_train_and_test_split_is_a_clear_error(tmp_path):
    with pytest.raises(LabelError):
        validate(tmp_path / "nothing")
    root = make_root(tmp_path, labels={"train": [(1, 0)]})                           # no test split
    with pytest.raises(LabelError):
        validate(root)
