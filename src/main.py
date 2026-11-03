import rp2
import uctypes
import time
import make_array
from array import array
from machine import Pin

HEIGHT,WIDTH=32,96   #HEIGHT*WIDTHDotMatrix
TOTAL_WORDS=HEIGHT*WIDTH
WORDS_PER_ROW=WIDTH/8
PIN_DATA_ARG=2        #GPIO 2,3,4 でAnode,Red,Greenのデータ転送
PIN_SCK=5             #GPIO 5,6,7 でSCK,LATCH,OEのデータ転送
PIN_LATCH=6
PIN_OE=7

SCK_freq = 2*1000*1000

COLOR = None

TG_RED=Pin(27,Pin.IN)
TG_GREEN=Pin(28,Pin.IN)
TG_1=Pin(12,Pin.IN)
TG_2=Pin(13,Pin.IN)
TG_3=Pin(14,Pin.IN)
TG_4=Pin(15,Pin.IN)

@rp2.asm_pio(
  out_init=(rp2.PIN.OUT_HIGH,rp2.PIO.OUT_LOW,rp2.PIO.OUT_LOW)*3,
  out_shiftdir=rp2.PIN.SHIFT_LEFT,
  sideset_init=(rp2.PIN.OUT_LOW,rp2.PIN.OUT_LOW,rp2.PIN.OUT_HIGH),
  fifo_join=rp2.PIO.JOIN_TX
  autopull=True,
  pull_thresh=24
)

def scan():
  wrap_target()

  set(y,3).side(0b100)           #4回繰り返し
  label("next_row")
  set(x,31).side(0)            #32回繰り返し(32bitぶん)
  label("next_bit")
  out(pins, 3).side(0b100)[1]     #3bit同時に取り出して出力、実行後、1サイクルdelay
  jmp(x_dec, "next_bit").side(0b101)[1]    #ScR_Xをインクリメントしてラベルに戻り、クロックを1進める
  jmp(y_dec, "next_row").side(0b101)[1]                      #ScR_Yをインクリメントしてラベルに戻る
  nop().side(0b100)
  nop().side(0b010)[1]
  nop().side(0b000)[1]

  wrap()

fb = array("I",[0]*HEIGHT*WORDS_PER_ROW)   #array("I",[0])で32bitであること,アノードがActive_lowであることに注意

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

COLBITS=tuple(
  (1 if c &0b01 else 0) | (1 if c & 0b10 else 0)
  for c in range(4)
)

ANODE_MASK = 0x92492400

def set_fb_static(src):
  if not len(src) == HEIGHT*WIDTH:
    raise ValueError("Error:データに過不足があります")
  for y in range(128):
    row_base=y*WIDTH
    sr_head=y*WORDS_PER_ROW
    for sr_pick in range(WORDS_PER_ROW):
      v=0
      for k in range(sr_pick*8,sr_pick*8+8):
        v=(v<<3) | COLBITS[src[k + row_base]]
      fb[sr_head+sr_pick] = (fb[sr_head+sr_pick] & ANODE_MASK | (v<<8))

sm = rp2.StateMachine(
  0,
  prog=scan,
  freq=SCK_freq * 4,
  out_base=Pin(PIN_DATA_ARG),
  sideset_base=Pin(PIN_SCK)
)

DMA_BASE=0x50000000     #DMAに割り当てられたベースアドレス
PIO0_TXF0=0x50200010    #DMAの中のPIO0のTX_FIFO0に割り当てられたアドレス

dma_data=rp2.DMA()
dma_count=rp2.DMA()
dma_addr=rp2.DMA()

transfer_count = array.array("I", [512])

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

def dma_transfer():

    dma.config(
        read=fb,
        write=PIO0_TXF0,
        count=128,
        ctrl=dma_ctrl,
        trigger=True
    )

def stop():
    #表示停止。1行だけ点灯し続けるとLEDを痛めるので、必ずOEをHighにしておく
    sm.active(0)
    dma_count.active(0)
    dma_data.active(0)
    Pin(PIN_OE, Pin.OUT, value=1)



sm.active(1)
dma_count.active(1)

while True:
# if TG_RED.value()==1 and TG_GREEN.value()==1:
#   COLOR=3
# elif TG_RED.value() == 1:
#   COLOR=1
# elif TG_GREEN.value() == 1:
#   COLOR=2
# else:
#   COLOR=None
  time.sleep(1)


