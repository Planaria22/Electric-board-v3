# 来場者メッセージを32x128ドットの ``array`` に変換する。

# ``make_array`` の戻り値は行優先 (上から下、左から右) の4096要素で、
# 各要素は無灯火=0、赤=1、緑=2、橙=3を表す。

# このモジュールではスクロールを行わない。128列を超える文字は右端で
# 切り捨てられ、短い文字列は残りの領域が無灯火になる。

from array import array
from pathlib import Path
from typing import Union

from text2led import HEIGHT, WIDTH, load_bdf, render


Color = Union[int, str]
DEFAULT_BDF = Path(__file__).with_name("jiskan24.bdf")

_COLOR_NAMES = {
    0: 0,
    1: 1,
    2: 2,
    3: 3,
    "off": 0,
    "none": 0,
    "red": 1,
    "green": 2,
    "orange": 3,
    "無灯火": 0,
    "消灯": 0,
    "赤": 1,
    "緑": 2,
    "橙": 3,
}


def _color_value(color: Color) -> int:
    """色名または色番号を、表示用の0〜3の値に変換する。"""
    key = color.lower() if isinstance(color, str) else color
    if isinstance(key, str) and key.isdigit():
        key = int(key)
    try:
        return _COLOR_NAMES[key]
    except (KeyError, TypeError):
        raise ValueError(
            "次のどれかを入力してください: '無灯火', '赤', '緑', '橙'"
        ) from None


def make_array(
    color: Color,
    text: str,
    bdf_path: Union[str, Path] = DEFAULT_BDF,
) -> array:
    # ``text`` を固定サイズのLEDフレームへ変換して返す
    # Args:
    #     color: 全文字に適用する色。0〜3、または色名を指定する。
    #     text: 来場者に表示する文字列。改行は無視する。
    #     bdf_path: 使用するBDFフォント。通常は省略できる。

    # Returns:
    #     ``array("I")`` 型の4096要素。要素の並びは行優先である。
    value = _color_value(color)
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if value == 0:
        return array("I", [0] * (WIDTH * HEIGHT))

    font, ascent = load_bdf(str(bdf_path))
    bitmap = render(text, font, ascent, default_color={1: "r", 2: "g", 3: "o"}[value])
    red, green = bitmap.window(0)

    pixels = (
        (3 if red[y][x] and green[y][x]
         else 1 if red[y][x]
         else 2 if green[y][x]
         else 0)
        for y in range(HEIGHT)
        for x in range(WIDTH)
    )
    return array("I", pixels)


def main() -> None:
    """コマンドラインから色と表示文字を受け取る簡易入力例。"""
    color = input("色 (0:無灯火, 1:赤, 2:緑, 3:橙): ")
    text = input("表示文字: ")
    frame = make_array(color, text)
    print(frame)


if __name__ == "__main__":
    main()
