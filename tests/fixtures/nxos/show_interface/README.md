# `show interface` fixture

`synthetic.txt` は設計書の解析 anchor に基づく合成入力であり、実機の収集結果ではない。
Ethernet、breakout、大文字・空白差、未知の down reason、admin 行欠落、および補完対象外の
management／subinterface／port-channel／SVI／loopback の block 境界を検証する。
NX-OS 9000v 10.5(4) および hardware の実機検証は未実施。
