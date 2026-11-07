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
    fifo_join=rp2.PIO.JOIN_TX
)
def led_pio():

    wrap_target()

    # 次の行データ待機
    pull(block).side(0b000)

    # シフト中はOE HIGH
    set(x, 7).side(0b100)

    label("bit")
    out(pins, 3).side(0b100)[1]
    jmp(x_dec, "bit").side(0b101)[1]

    # ラッチ
    nop().side(0b100)
    nop().side(0b110)
    nop().side(0b100)

    # OE LOW：表示開始
    nop().side(0b000)

    set(y, 31).side(0b000)

    label("dwell")
    jmp(y_dec, "dwell").side(0b000)[1]

    wrap()


# =========================================
# データ生成
# =========================================

def pack_data(anode, red, green):

    word = 0

    for bit in range(7, -1, -1):

        value = (
            ((anode >> bit) & 1)
            | (((red >> bit) & 1) << 1)
            | (((green >> bit) & 1) << 2)
        )

        word = (word << 3) | value

    return word << 8


# =========================================
# 8行フレームバッファ
# =========================================

fb = array.array("I", [0] * 8)


def make_checkerboard():

    for y in range(8):

        red = 0

        for x in range(8):

            if (x + y) % 2 == 0:
                red |= 1 << x

        # 1行だけアノードを有効化
        anode = 1 << y

        fb[y] = pack_data(
            anode,
            red,
            0x00
        )


# =========================================
# PIO
# =========================================

sm = rp2.StateMachine(
    0,
    led_pio,
    freq=4_000_000,
    out_base=Pin(2),
    sideset_base=Pin(5)
)


# =========================================
# DMA
# =========================================

PIO0_TXF0 = 0x50200010

PIO0_TXF0 = 0x50200010

# DMAチャネル
dma_data = rp2.DMA()
dma_count = rp2.DMA()
dma_addr = rp2.DMA()

# DMA転送数
transfer_count = array.array("I", [8])

# フレームバッファ先頭アドレス
fb_addr = array.array(
    "I",
    [uctypes.addressof(fb)]
)

# -----------------------------------------
# DMA 3：データ転送
# -----------------------------------------

dma_data.config(
    read=fb,
    write=PIO0_TXF0,
    count=8,
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
        count=8,
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

