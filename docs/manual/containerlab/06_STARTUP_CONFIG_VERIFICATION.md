# Startup Config Verification

## 1. 目的

lab 起動後の running config と、`clab-transform-config`が生成した期待 config を read-only で比較する。
差分を自動修正したり設定投入したりしない。

NX-OS 9000v へ boot 後に`push-config-dir`で投入する workflow でも、`raw/labconfig/`を期待 config として使用する。

## 2. 実行

```bash
alred check-clab-startup-config \
  --hosts hosts.lab.yaml \
  --credentials clab_credentials.yaml \
  --startup-dir raw/labconfig \
  --file-suffix _run.txt \
  --output-dir output/check-clab-startup-config \
  --workers 5
```

一部nodeだけ確認する場合:

```bash
alred check-clab-startup-config \
  --hosts hosts.lab.yaml \
  --ask-pass \
  --startup-dir raw/labconfig \
  --target-hosts lab-leaf01,lab-leaf02
```

## 3. 結果

statusは`matched`、`diff`、`missing-startup`、`unsupported`、`connect-failed`、`failed`を区別する。

```text
output/check-clab-startup-config/
├── current/
└── check-clab-startup-config.txt
```

`diff`は投入元、起動log、image capability、動的lineの正規化規則を確認する。接続失敗時もinventoryからdevice typeを
解決し、`connect-failed`としてreportを生成する。この取得はCollection Manifestへ未統合である。
