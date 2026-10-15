import rp2
from machine import Pin

HEIGHT,WIDTH=32,128   #32*128DotMatrix
PIN_DATA_AGR=2        #GPIO 2,3,4 でAnode,Green,Redのデータ転送
PIN_SCK_LATCH_OE=5    #GPIO 5,6,7 でSCK,LATCH,OEのデータ転送

SCK_freq = 2*1000*1000


@rp2.asm_pio(
  out_init=(rp2.PIO.OUT_LOW)*3,
  out_shiftdir=rp2.PIN.SHIFT_LEFT,
  fifo_join=(rp2.PIO.JOIN_TX)
)

sm = rp2.StateMachine(
  0,
  
)