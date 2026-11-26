"""A tiny synthetic digit dataset in the ids layout, for fast tests of the training and evaluation code."""
from PIL import Image, ImageDraw, ImageFont


def make_digit_dataset(root, n_train=21, n_val=9, n_test=11):
    words = [f"{a}{b}" for a in "0123" for b in "0123"]
    (root / "vocab.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
    font = ImageFont.load_default(size=26)
    for split, n in (("train", n_train), ("val", n_val), ("test", n_test)):
        (root / split).mkdir()
        rows = []
        for k in range(1, n + 1):
            wid = (k * 7) % len(words)
            img = Image.new("L", (80, 40), 255)
            ImageDraw.Draw(img).text((8, 4), words[wid], fill=0, font=font)
            img.save(root / split / f"{k}.jpg")
            rows.append(f"{split}/{k}.jpg, {wid}")
        (root / f"{split}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root
