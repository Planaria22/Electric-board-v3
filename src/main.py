import rp2
import uctypes
import time
from array import array
from machine import Pin

HEIGHT,WIDTH=32,128   #HEIGHT*WIDTHDotMatrix
TOTAL_WORDS=HEIGHT*WIDTH
WORDS_PER_ROW=WIDTH/4
PIN_DATA_ARG=0        #GPIO 0,1,2 でAnode,Red,Greenのデータ転送
PIN_SCK=4             #GPIO 4,5,6 でSCK,LATCH,OEのデータ転送
PIN_LATCH=5
PIN_OE=6
POWER_PIN=12
COLOR_PINS=[27,28]  #Red,Green
MODE_PINS=[13,14,15]

SCK_freq = 10_000_000

power=Pin(POWER_PIN,Pin.IN)
color_switches=[Pin(pin,Pin.IN) for pin in COLOR_PINS]
mode_switches=[Pin(pin,Pin.IN) for pin in MODE_PINS]

led = Pin('LED', Pin.OUT)

@rp2.asm_pio(
  out_init=(rp2.PIO.OUT_HIGH,rp2.PIO.OUT_LOW,rp2.PIO.OUT_LOW)*3,
  out_shiftdir=rp2.PIO.SHIFT_LEFT,
  sideset_init=(rp2.PIO.OUT_LOW,rp2.PIO.OUT_LOW,rp2.PIO.OUT_HIGH),
  fifo_join=rp2.PIO.JOIN_TX,
  autopull=True,
  pull_thresh=24
)

def scan(): #OE,LATCH,SCK
  wrap_target()

  set(y,3).side(0b100)           #4回繰り返し
  label("next_board")
  set(x,31).side(0b100)            #32回繰り返し(128bitぶん)
  label("next_bit")
  out(pins, 3).side(0b100)[1]     #3bit同時に取り出して出力、実行後、1サイクルdelay
  jmp(x_dec, "next_bit").side(0b101)[1]    #ScR_Xをインクリメントしてラベルに戻り、クロックを1進める
  jmp(y_dec, "next_board").side(0b100)[1]                      #ScR_Yをインクリメントしてラベルに戻る
  nop().side(0b100)
  nop().side(0b010)[3]
  nop().side(0b000)[3]

  wrap()

fb = array("I",[0]*32*16)   #array("I",[0])で32bitであること,アノードがActive_lowであることに注意

def pack_row(anode, red, green):
  words = []
  for group in range(16):
    word = 0
    # 8画素分
    for i in range(8):
      k = group * 8 + i
      col = 127 - k
      if k < 96:
        a=1
      else:
        a=(anode>>(31-(k-96))) & 1
      r=(red>>col) & 1
      g=(green>>col) & 1
      value = (
        a| (r << 1) | (g << 2)
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
        for i in range(16):
            fb[y * 16 + i] = words[i]

def make_checkerboard():
    for y in range(32):
        anode = (~(1 << y)) & 0xFFFFFFFF
        red = 0
        green = 0
        for x in range(128):
            if (x + y) % 2 == 0:
                green |= (1 << x)
        words = pack_row(anode, red, green)
        for i in range(16):
            fb[y * 16 + i] = words[i]

def load_frame(src):
  if len(src) != WIDTH * HEIGHT:
    raise ValueError("frame size must be 4096")

  for y in range(HEIGHT):

    # アノードは選択行のみLOW
    anode = 0xFFFFFFFF ^ (1 << y)

    red = 0
    green = 0

    for x in range(WIDTH):

      value = src[y * WIDTH + x]

      if value == 0:
        continue

      # 32x32ブロック単位で左90度回転
      block = x // 32
      local_x = x % 32

      # 物理カソードの位置
      cathode = block * 32 + (31 - local_x)

      if value & 1:
        red |= 1 << cathode

      if value & 2:
        green |= 1 << cathode

    words = pack_row(anode, red, green)

    # DMAが参照するfb自体は作り直さない
    for i in range(16):
        fb[y * 16 + i] = words[i]

def stop():
    sm.active(0)
    dma_count.active(0)
    dma_data.active(0)
    Pin(PIN_OE, Pin.OUT, value=1)

def read_binary_switches(switches):
    """
    複数のスイッチをビット値に変換する。

    例:
    [0, 1] -> 2
    [1, 0] -> 1
    [1, 1] -> 3
    """
    value = 0
    for bit, switch in enumerate(switches):
        value |= switch.value() << bit
    return value

def apply_settings(power_on, color, mode):
  if not power_on:
    stop()
    return
  if display_mode == 0:
    sm.active(1)
    dma_count.active(1)
    make_checkerboard()
  else:
    make_blank()
  
last_state=0

sm = rp2.StateMachine(
  0,
  prog=scan,
  freq=SCK_freq,
  out_base=Pin(PIN_DATA_ARG),
  sideset_base=Pin(PIN_SCK)
)

DMA_BASE=0x50000000     #DMAに割り当てられたベースアドレス
PIO0_TXF0=0x50200010    #DMAの中のPIO0のTX_FIFO0に割り当てられたアドレス

dma_data=rp2.DMA()
dma_count=rp2.DMA()
dma_addr=rp2.DMA()

transfer_count = array("I", [512])

fb_addr=array("I",uctypes.addressof(fb))  #fbの先頭アドレスを取得

dma_addr.pack_ctrl(
  size=2,
  inc_read=False,
  inc_write=False,
  treq_sel=0x3f,
  chain_to=dma_data.channel
)
dma_count.pack_ctrl(
  size=2,
  inc_read=False,
  inc_write=False,
  treq_sel=0x3f,       #Permanent request、気にしないでいい
  chain_to=dma_addr.channel
)
dma_data.pack_ctrl(
  size=2,
  inc_read=True,              #読み出しアドレスを増加
  inc_write=False,
  treq_sel=0,                 #PIO0のTXFIFOと転送を同期
  chain_to=dma_count.channel   #完了後dma_ctrlを実行
)

dma_addr.config(
  read=fb_addr,
  write=dma_data.registers[15:16],
  count=1,
  ctrl=dma_addr.pack_ctrl
)
dma_count.config(
  read=transfer_count,
  write=dma_data.resisters[14:15],
  count=1,
  ctrl=dma_count.pack_ctrl
)
dma_data.config(
  read=fb,
  write=PIO0_TXF0,
  count=512,        #再計算されず2回目は0のままかもー？
  ctrl=dma_data.pack_ctrl,
  trigger=True
)

sm.active(1)
dma_count.active(1)

while True:
  power_on = bool(power.value())
  color_mode=read_binary_switches(color_switches)
  display_mode=read_binary_switches(mode_switches)

  current_state=(power,color_mode,display_mode)
  if current_state != last_state:
    time.sleep_ms(50)
    power_on = bool(power.value())
    color_mode=read_binary_switches(color_switches)
    display_mode=read_binary_switches(mode_switches)

    confirmed_state = (power_on, color_mode, display_mode)
    if confirmed_state != last_state:
      apply_settings(power_on, color_mode, display_mode)

      last_state = confirmed_state


