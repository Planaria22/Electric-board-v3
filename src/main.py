import rp2
import uctypes
from array import array
from machine import Pin

HEIGHT,WIDTH=32,128   #32*128DotMatrix
SR_PER_ROW=WIDTH/8
PIN_DATA_ARG=2        #GPIO 2,3,4 でAnode,Red,Greenのデータ転送
PIN_SCK=5             #GPIO 5,6,7 でSCK,LATCH,OEのデータ転送
PIN_LATCH=6
PIN_OE=7

SCK_freq = 2*1000*1000
fb = array("I",[0]*HEIGHT*SR_PER_ROW)   #array("I",[0])で32bitであること,アノードがActive_lowであることに注意
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
)

def scan():
  wrap_target()

  set(y,15).side(0)           #16回繰り返し
  label("next_row")
  pull(block).side(0)         #TX_FIFOからOSRへデータを引き込む
  set(x,7).side(0)            #8回繰り返し(8bitぶん)
  label("next_bit")
  out(pins, 3).side(0)[1]     #3bit同時に取り出して出力、実行後、1サイクルdelay
  jmp(x_dec, "next_bit").side(PIN_SCK)[1]    #ScR_Xをインクリメントしてラベルに戻り、クロックを1進める
  jmp(y_dec, "next_row").side(0)                      #ScR_Yをインクリメントしてラベルに戻る
  nop().side(PIN_OE)
  nop().side(PIN_OE | PIN_LATCH)[1]
  nop().side(PIN_OE)

  wrap()

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
dma_ctrl=rp2.DMA()

fb_addr=array("I",uctypes.addressof(fb))  #fbの先頭アドレスを取得

def start():
  dma_ctrl.pack_ctrl(
    size=2,
    inc_read=False,
    inc_write=False,
    treq_sel=0x3f       #Permanent request、気にしないでいい
  )
  dma_data.pack_ctrl(
    size=2,
    inc_read=True,              #読み出しアドレスを増加
    inc_write=False,
    treq_sel=0,                 #PIO0のTXFIFOと転送を同期
    chain_to=dma_ctrl.channel   #完了後dma_ctrlを実行
  )
  dma_ctrl.config(  #fbの読み出しアドレスを先頭に戻す
    read=fb_addr,
    write=DMA_BASE + 0x40*dma_data.channel + 0x3c,  #0x40:dmaチャネルの幅、0x3c:READ_ADD_TRIG
    count=1,
    ctrl=dma_ctrl.pack_ctrl
  )
  dma_data.config(
    read=fb,
    write=PIO0_TXF0,
    count=len(fb),        #再計算されず2回目は0のままかもー？
    ctrl=dma_data.pack_ctrl,
    trigger=True
  )
  sm.active(1)

def stop():
    """表示停止。1行だけ点灯し続けるとLEDを痛めるので、必ずOEをHighにしておく"""
    sm.active(0)
    dma_ctrl.active(0)
    dma_data.active(0)
    Pin(PIN_OE, Pin.OUT, value=1)

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
    sr_head=y*SR_PER_ROW
    for sr_pick in range(SR_PER_ROW):
      v=0
      for k in range(sr_pick*8,sr_pick*8+8):
        v=(v<<3) | COLBITS[src[k + row_base]]
      fb[sr_head+sr_pick] = (fb[sr_head+sr_pick] & ANODE_MASK | (v<<8))



start()
while True:
  if TG_RED.value()==1 and TG_GREEN.value()==1:
    COLOR=3
  elif TG_RED.value() == 1:
    COLOR=1
  elif TG_GREEN.value() == 1:
    COLOR=2
  else:
    COLOR=None


