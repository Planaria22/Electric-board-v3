# Raspberry Pi Pico (MicroPython)
# 74HC595 使用 32 x 128 二色(赤/緑) LED 電光掲示板 ダイナミック点灯
#
# 配線 (GPIO)
#   GP2 : MOSI0 -> 赤カソード 595 チェーン (128bit) の SER
#   GP3 : MOSI1 -> 緑カソード 595 チェーン (128bit) の SER
#   GP4 : MOSI2 -> アノード   595 チェーン ( 32bit) の SER
#   GP5 : SCK   -> 全 595 の SRCLK (共通)
#   GP6 : LATCH -> 全 595 の RCLK  (共通)
#   GP7 : OE    -> 全 595 の /OE   (共通, High でブランク)
#
# 仕組み
#   ・1行分 = 128クロック。1クロックごとに MOSI0/1/2 の3bitを同時に出力
#   ・アノードは32bitしかないので、128クロックのうち「最後の32クロック」に
#     本物のデータを載せ、最初の96クロックはダミー(行非選択)にする
#   ・1ワード(32bit)に 3bit x 8クロック = 24bit を左詰めで格納 -> 1行 = 16ワード
#   ・PIO が 128クロック送出 -> OE=High -> LATCH パルス -> OE=Low を自動で行う
#   ・DMA が全32行ぶん(512ワード)をループで PIO に送り続ける

import time
import rp2
import uctypes
from array import array
from machine import Pin

# ---------------- 設定 ----------------
WIDTH, HEIGHT = 128, 32
WORDS_PER_ROW = WIDTH // 8          # 16

PIN_DATA = 2                        # GP2, GP3, GP4 を連続して使う
PIN_SCK = 5                         # GP5, GP6, GP7 を連続して使う
PIN_LATCH = 6
PIN_OE = 7

SCK_HZ = 2_000_000                  # SCK 周波数 (2MHz -> 約440Hzで全画面更新)

COL_ON = 0                          # カソード側: 0 で点灯 (逆なら 1)
COL_OFF = 1 - COL_ON
ROW_ON = 0                          # アノード側: 選択行が 0 (仕様どおり)
ROW_OFF = 1 - ROW_ON

X_FLIP = False                      # 表示が左右反転していたら True
Y_FLIP = False                      # 表示が上下反転していたら True

OFF, RED, GREEN, ORANGE = 0, 1, 2, 3

# サイドセット: bit0=SCK, bit1=LATCH, bit2=OE
S_SCK = 1
S_LATCH = 2
S_OE = 4


# ---------------- PIO ----------------
@rp2.asm_pio(
    out_init=(rp2.PIO.OUT_LOW,) * 3,                                  # MOSI0,1,2
    sideset_init=(rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH),  # SCK, LATCH, OE
    out_shiftdir=rp2.PIO.SHIFT_LEFT,
    fifo_join=rp2.PIO.JOIN_TX,
)
def led_row():
    wrap_target()
    set(y, 15).side(0)                        # 16ワード = 128クロック
    label("word")
    pull(block).side(0)
    set(x, 7).side(0)                         # 1ワード = 8クロック
    label("bit")
    out(pins, 3).side(0)[1]                   # SCK Low: 3本同時にデータ出力
    jmp(x_dec, "bit").side(S_SCK)[1]          # SCK High: 立ち上がりでシフト
    jmp(y_dec, "word").side(0)
    # 1行ぶんシフト完了 -> ブランクしてラッチ
    nop().side(S_OE)[1]
    nop().side(S_OE | S_LATCH)[1]
    nop().side(S_OE)[1]
    wrap()


# ---------------- フレームバッファ ----------------
# fb[y * 16 + n] の n 番目ワードに、クロック 8n .. 8n+7 の3bit(R,G,アノード)を格納
fb = array("I", [0]) * (HEIGHT * WORDS_PER_ROW)


def _sel_clock(y):
    """行 y を選択するアノードbitを送るクロック番号 (96..127)"""
    q = (HEIGHT - 1 - y) if Y_FLIP else y
    return 127 - q


def fill(color=OFF):
    r = COL_ON if color & 1 else COL_OFF
    g = COL_ON if color & 2 else COL_OFF
    cols = r | (g << 1)
    for y in range(HEIGHT):
        sel = _sel_clock(y)
        for wi in range(WORDS_PER_ROW):
            w = 0
            for j in range(8):
                k = wi * 8 + j
                a = ROW_ON if k == sel else ROW_OFF
                w |= (cols | (a << 2)) << (29 - 3 * j)
            fb[y * WORDS_PER_ROW + wi] = w


def clear():
    fill(OFF)


def set_pixel(x, y, color):
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return
    p = (WIDTH - 1 - x) if X_FLIP else x   # チェーン内の位置 (0 = 先頭の595)
    k = WIDTH - 1 - p                      # その位置に届くbitを送るクロック番号
    idx = y * WORDS_PER_ROW + (k >> 3)
    s = 29 - 3 * (k & 7)
    r = COL_ON if color & 1 else COL_OFF
    g = COL_ON if color & 2 else COL_OFF
    fb[idx] = (fb[idx] & (0xFFFFFFFF ^ (3 << s))) | ((r | (g << 1)) << s)


# ---------------- 起動 / 停止 ----------------
DMA_BASE = 0x50000000
PIO0_TXF0 = 0x50200010                      # PIO0 ステートマシン0 の TX FIFO

clear()

sm = rp2.StateMachine(
    0, led_row,
    freq=SCK_HZ * 4,                        # 1ビット = 4 PIOサイクル
    out_base=Pin(PIN_DATA),
    sideset_base=Pin(PIN_SCK),
)

dma_data = rp2.DMA()                        # fb -> PIO
dma_ctrl = rp2.DMA()                        # 終了後に dma_data の読み出し位置を先頭へ戻す
_fb_addr = array("I", [uctypes.addressof(fb)])


def start():
    dma_ctrl.config(
        read=_fb_addr,
        write=DMA_BASE + 0x40 * dma_data.channel + 0x3C,   # READ_ADDR_TRIG
        count=1,
        ctrl=dma_ctrl.pack_ctrl(size=2, inc_read=False, inc_write=False, treq_sel=0x3F),
    )
    dma_data.config(
        read=fb,
        write=PIO0_TXF0,
        count=len(fb),
        ctrl=dma_data.pack_ctrl(size=2, inc_read=True, inc_write=False,
                                treq_sel=0, chain_to=dma_ctrl.channel),
        trigger=True,
    )
    sm.active(1)


def stop():
    """表示停止。1行だけ点灯し続けるとLEDを痛めるので、必ずOEをHighにしておく"""
    sm.active(0)
    dma_ctrl.active(0)
    dma_data.active(0)
    Pin(PIN_OE, Pin.OUT, value=1)


# ---------------- デモ ----------------
def _stripe(y):
    return RED if y < 11 else (GREEN if y < 22 else ORANGE)


def demo():
    for y in range(HEIGHT):
        for x in range(WIDTH):
            set_pixel(x, y, _stripe(y))
    x = 0
    while True:
        for y in range(HEIGHT):
            set_pixel(x, y, OFF)
        time.sleep_ms(15)
        for y in range(HEIGHT):
            set_pixel(x, y, _stripe(y))
        x = (x + 1) % WIDTH


if __name__ == "__main__":
    start()
    try:
        demo()
    except KeyboardInterrupt:
        stop()