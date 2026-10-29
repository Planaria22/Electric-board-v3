# 文字列 -> 32x128 2色LED電光掲示板用データ変換 (jiskan24.bdf 使用)

# 流れ:  文字列 --(Unicode->JIS X 0208)--> BDFグリフ(24x24) --> 赤/緑ビットマップ
#         --(128列の窓で切り出し)--> フレーム --> 74HC595へ送るバイト列

# 色タグ:  {r}赤  {g}緑  {o}橙  を文字列中に書くと以降の文字の色が変わる
#          例: "{r}停止{g}運転中{o}注意"

import re
import sys
import unicodedata

WIDTH, HEIGHT = 128, 32           # 表示全体
GLYPH = 24                        # フォントサイズ
TOP_MARGIN = (HEIGHT - GLYPH) // 2  # 縦中央寄せ (4px)
COLORS = {"r": (1, 0), "g": (0, 1), "o": (1, 1)}   # (赤, 緑)  橙=同時点灯


# ---------------------------------------------------------------- BDF
def load_bdf(path):
    font, ascent = {}, 22
    code = bbx = None
    rows, in_bitmap = [], False
    with open(path, encoding="ascii", errors="ignore") as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            k = t[0]
            if k == "FONT_ASCENT":
                ascent = int(t[1])
            elif k == "ENCODING":
                code = int(t[1])
            elif k == "BBX":
                bbx = tuple(map(int, t[1:5]))
            elif k == "BITMAP":
                in_bitmap, rows = True, []
            elif k == "ENDCHAR":
                in_bitmap = False
                if code is not None and code >= 0 and bbx:
                    w, h, xo, yo = bbx
                    # 行を「左端=最上位ビット」のw桁整数へ
                    pad = ((w + 7) // 8) * 8 - w
                    font[code] = (w, h, xo, yo, [r >> pad for r in rows])
                code = bbx = None
            elif in_bitmap:
                rows.append(int(k, 16))
    return font, ascent


# ---------------------------------------------------------------- 文字コード
def to_jis(ch):
    if ch == " ":
        ch = "　"
    elif "!" <= ch <= "~" and ch not in "\\~":
        ch = chr(ord(ch) + 0xFEE0)          # ASCII -> 全角
    elif ch == "\\":
        ch = "＼"
    elif ch == "~":
        ch = "～"
    else:
        n = unicodedata.normalize("NFKC", ch)   # 半角カナ等 -> 全角
        ch = n if len(n) == 1 else ch
    try:
        b = ch.encode("euc_jp")
    except UnicodeEncodeError:
        return None
    if len(b) != 2:
        return None
    return ((b[0] << 8) | b[1]) - 0x8080


def parse_markup(text, default="o"):
    out, color = [], default
    for tok in re.split(r"(\{[rgo]\})", text):
        if re.fullmatch(r"\{[rgo]\}", tok):
            color = tok[1]
        else:
            out.extend((c, color) for c in tok if c not in "\r\n")
    return out


# ---------------------------------------------------------------- 描画
class Bitmap:
    # 赤/緑 2枚の 32行 x N列 ビットマップ (値は0/1のリスト)

    def __init__(self, width):
        self.width = width
        self.red = [[0] * width for _ in range(HEIGHT)]
        self.green = [[0] * width for _ in range(HEIGHT)]

    def window(self, offset=0):
        # offset列目から128列を切り出す (範囲外は消灯)
        def cut(plane):
            return [[(r[x] if 0 <= x < self.width else 0)
                     for x in range(offset, offset + WIDTH)] for r in plane]
        return cut(self.red), cut(self.green)


def render(text, font, ascent, default_color="o", spacing=0, missing_code=0x2121):
    items = parse_markup(text, default_color)
    bmp = Bitmap(max(1, len(items) * (GLYPH + spacing)))
    baseline = TOP_MARGIN + ascent
    for i, (ch, col) in enumerate(items):
        code = to_jis(ch)
        g = font.get(code) or font.get(missing_code)
        if g is None:
            continue
        w, h, xo, yo, rows = g
        r_on, g_on = COLORS[col]
        x0 = i * (GLYPH + spacing) + xo
        y0 = baseline - (yo + h)
        for dy, bits in enumerate(rows):
            y = y0 + dy
            if not 0 <= y < HEIGHT:
                continue
            for dx in range(w):
                if bits >> (w - 1 - dx) & 1:
                    x = x0 + dx
                    if 0 <= x < bmp.width:
                        bmp.red[y][x] = r_on
                        bmp.green[y][x] = g_on
    return bmp


# ---------------------------------------------------------------- 595用データ
def pack_bits(bits):
    # 0/1列 -> バイト列 (先頭ビット=最上位、最初に送出される)
    bits = list(bits) + [0] * (-len(bits) % 8)
    return bytes(sum(b << (7 - j) for j, b in enumerate(bits[i:i + 8]))
                 for i in range(0, len(bits), 8))


def frame_to_scan_data(red, green, active_low=True):
    # 1フレーム(32x128) -> 走査16行分のバイト列リスト。

    packets = []
    for r in range(16):
        sel = pack_bits([1 if i == r else 0 for i in range(16)])
        data = bytearray(sel)
        for plane, row in ((red, r), (green, r), (red, r + 16), (green, r + 16)):
            bits = plane[row][::-1]
            if active_low:
                bits = [b ^ 1 for b in bits]
            data += pack_bits(bits)
        packets.append(bytes(data))
    return packets


# ---------------------------------------------------------------- 確認用
def preview(red, green):
    ch = {(0, 0): "·", (1, 0): "R", (0, 1): "G", (1, 1): "O"}
    return "\n".join("".join(ch[(red[y][x], green[y][x])] for x in range(len(red[y])))
                     for y in range(len(red)))


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "jiskan24.bdf"
    text = sys.argv[2] if len(sys.argv) > 2 else "{r}電光{g}掲示板{o}OK"
    font, ascent = load_bdf(path)
    bmp = render(text, font, ascent)
    red, green = bmp.window(0)
    print(preview(red, green))
    pk = frame_to_scan_data(red, green)
    print(f"\n幅 {bmp.width}列 / 走査行数 {len(pk)} / 1行 {len(pk[0])}バイト")
    print("row0:", pk[0].hex())