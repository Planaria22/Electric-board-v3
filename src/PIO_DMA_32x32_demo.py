
import rp2
import array
import uctypes
import time
from machine import Pin

# =========================================
# PIO
# GP2: Anode
# GP3: Red cathode
# GP4: Green cathode
# GP5: SCK
# GP6: LATCH
# GP7: OE
# =========================================


@rp2.asm_pio(
    out_init=(rp2.PIO.OUT_LOW,) * 3,
    sideset_init=(
        rp2.PIO.OUT_LOW,
        rp2.PIO.OUT_LOW,
        rp2.PIO.OUT_LOW
    ),
    out_shiftdir=rp2.PIO.SHIFT_LEFT,
    autopull=True,
    pull_thresh=24,
    fifo_join=rp2.PIO.JOIN_TX
)
def led_pio_32():

    wrap_target()

    # 32画素分を出力
    set(x, 31).side(0b100)

    label("bit")
    out(pins, 3).side(0b100)[1]
    jmp(x_dec, "bit").side(0b101)[1]

    # ラッチ
    nop().side(0b100)
    nop().side(0b010)
    nop().side(0b000)

    # 表示
    nop().side(0b000)

    # 表示時間
    set(y, 31).side(0b000)

    label("dwell")
    jmp(y_dec, "dwell").side(0b000)[3]

    wrap()


# =========================================
# データ生成
# =========================================

WIDTH = 32
HEIGHT = 32

# 32行 × 4ワード
fb = array.array("I", [0] * 128)


def pack_row(anode, red, green):

    words = []

    for group in range(4):

        word = 0

        # 8画素分
        for i in range(8):

            col = 31 - (group * 8 + i)

            value = (
                ((anode >> col) & 1)
                | (((red >> col) & 1) << 1)
                | (((green >> col) & 1) << 2)
            )

            word = (word << 3) | value

        # 24bitを上位側へ配置
        words.append(word << 8)

    return words


def make_checkerboard():

    for y in range(32):

        red = 0

        for x in range(32):

            if (x + y) % 2 == 0:
                red |= 1 << x

        anode = 1 << y

        words = pack_row(anode, red, 0)

        for i in range(4):
            fb[y * 4 + i] = words[i]


# =========================================
# PIO
# =========================================

sm = rp2.StateMachine(
    0,
    led_pio_32,
    freq=4_000_000,
    out_base=Pin(2),
    sideset_base=Pin(5)
)


# =========================================
# DMA
# =========================================

PIO0_TXF0 = 0x50200010

# DMAチャネル
dma_data = rp2.DMA()
dma_count = rp2.DMA()
dma_addr = rp2.DMA()

# DMA転送数8ワード → 128ワード
transfer_count = array.array("I", [128])

# フレームバッファ先頭アドレス
fb_addr = array.array("I",[uctypes.addressof(fb)])

# -----------------------------------------
# DMA 3：データ転送
# -----------------------------------------

dma_data.config(
    read=fb,
    write=PIO0_TXF0,
    count=128,
    ctrl=dma_data.pack_ctrl(
        size=2,
        inc_read=True,
        inc_write=False,
        treq_sel=0,               # PIO0 TX0
        chain_to=dma_count.channel
    )
)

# -----------------------------------------
# DMA 1：転送数設定
# -----------------------------------------

dma_count.config(
    read=transfer_count,
    write=dma_data.registers[14:15],
    count=1,
    ctrl=dma_count.pack_ctrl(
        size=2,
        inc_read=False,
        inc_write=False,
        treq_sel=0x3F,
        chain_to=dma_addr.channel
    )
)

# -----------------------------------------
# DMA 2：読み出しアドレス設定
# -----------------------------------------

dma_addr.config(
    read=fb_addr,
    write=dma_data.registers[15:16],
    count=1,
    ctrl=dma_addr.pack_ctrl(
        size=2,
        inc_read=False,
        inc_write=False,
        treq_sel=0x3F,
        chain_to=dma_data.channel
    )
)

def dma_transfer():

    dma.config(
        read=fb,
        write=PIO0_TXF0,
        count=128,
        ctrl=dma_ctrl,
        trigger=True
    )

# =========================================
# メイン
# =========================================

make_checkerboard()

sm.active(1)

# DMA 1から開始
dma_count.active(1)

# 以後、DMA 1 → DMA 2 → DMA 3 → DMA 1 ...
while True:
    time.sleep(1)
