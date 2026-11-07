import rp2
import array
import uctypes
import time
from machine import Pin

# =========================================
# PIO
# GP0: Anode
# GP1: Red cathode
# GP2: Green cathode
# GP4: SCK
# GP5: LATCH
# GP6: OE
# =========================================


@rp2.asm_pio(
    out_init=(rp2.PIO.OUT_LOW,) * 3,
    sideset_init=(rp2.PIO.OUT_LOW,rp2.PIO.OUT_LOW,rp2.PIO.OUT_LOW),
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
    out(pins, 3).side(0b100)
    jmp(x_dec, "bit").side(0b101)
    
    # ラッチ
    nop().side(0b100)
    nop().side(0b010)[3]
    nop().side(0b000)[3]

    # 表示
    

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

def make_blank():

    for y in range(32):

        anode = 0xFFFFFFFF
        red = 0
        green = 0

        words = pack_row(anode, red, green)

        for i in range(4):
            fb[y * 4 + i] = words[i]

def make_test():

    for y in range(32):
        green=0
        red = 0
        anode = (~(1 << y)) & 0xFFFFFFFF

        if y == 17:
            red = 1 << 0

        words = pack_row(anode, red, green)

        for i in range(4):
            fb[y * 4 + i] = words[i]

def make_green_test():

    for y in range(32):

        anode = (~(1 << y)) & 0xFFFFFFFF
        red = 0
        green = 0xFFFFFFFF if y == 17 else 0

        words = pack_row(anode, red, green)

        for i in range(4):
            fb[y * 4 + i] = words[i]

def make_checkerboard():

    for y in range(32):

        anode = 0xFFFFFFFF
        red = 0
        green = 0

        for x in range(32):

            # 市松模様
            if (x + y) % 2 == 0:
                anode &= ~(1 << y)
                green |= (1 << x)

        words = pack_row(anode, red, green)

        for i in range(4):
            fb[y * 4 + i] = words[i]
# =========================================
# PIO
# =========================================

sm = rp2.StateMachine(
    0,
    led_pio_32,
    freq=20_000_000,
    out_base=Pin(0),
    sideset_base=Pin(4)
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

# def dma_transfer():
# 
#     dma.config(
#         read=fb,
#         write=PIO0_TXF0,
#         count=128,
#         ctrl=dma_ctrl,
#         trigger=True
#     )

# =========================================
# メイン
# =========================================

make_checkerboard()
print([hex(fb[i]) for i in range(4)])
print([hex(fb[i]) for i in range(4, 8)])

dma_count.active(1)
sm.active(1)

FDEBUG = 0x50200008
TXSTALL_SM0 = 1 << 24

# TXSTALLをクリア
machine.mem32[FDEBUG] = TXSTALL_SM0

time.sleep_ms(100)

print("FDEBUG:", hex(machine.mem32[FDEBUG]))
print("TXSTALL:", (machine.mem32[FDEBUG] >> 24) & 1)
while True:
    time.sleep_ms(100)
    
