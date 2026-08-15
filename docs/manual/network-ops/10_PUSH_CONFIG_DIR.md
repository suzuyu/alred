# push-config-dir Guide

`push-config-dir` は、inventory の host ごとに異なる config file を直接投入する command です。投入は
running-config を変更しますが、change ID、approval、automatic rollback、after Health Check は作成しません。
投入前後の Health Check と明示的な保存を含む標準手順は
[Direct Config Push Quick Start](./12_DIRECT_CONFIG_PUSH_QUICK_START.md)を参照してください。
監査可能な変更管理が必要な場合は
[alred Overlay Change Apply](./08_ALRED_OVERLAY_CHANGE_APPLY.md)を使用してください。

正式な安全仕様は
[Direct Config Push and Save Design](../../design/network-ops/DIRECT_CONFIG_PUSH_AND_SAVE_DESIGN.md#33-nx-os-接続保護-filter)
を正本とします。

## 1. 入力 file を準備

既定の exact mode では、`<hostname><suffix>` と一致する file を host へ対応付けます。

```text
raw/config/
├── leaf01_run.txt
└── leaf02_run.txt
```

次の例では `leaf01` に `raw/config/leaf01_run.txt` を投入します。

```bash
alred push-config-dir \
  --hosts hosts.yaml \
  --input-dir raw/config \
  --file-suffix _run.txt \
  --target-hosts leaf01,leaf02 \
  --workers 1
```

対象表示後に `yes` と入力した場合だけ投入を開始します。`--write-memory` 未指定時は running-config を
startup-config へ保存しません。

## 2. NX-OS 接続保護 filter

NX-OS では、投入に使用している認証と management 接続を途中で失わないよう、次の config を既定で除外します。

| 対象 | 既定動作 |
|---|---|
| 接続に使用した `username <login-user> ...` と `no username <login-user>` | login username が大文字・小文字を含めて完全一致する command だけを除外 |
| `vrf context management` | section 全体を除外 |
| `interface mgmt0` | section 全体を除外 |
| `line vty`／`line vty <range>` | section 全体を除外 |
| management VRF、`mgmt0`、VTY の削除／初期化 command | 該当 command を除外 |

別 user の `username` command は除外しません。次のように別 section から `mgmt0` を参照する command も
除外しません。

```text
logging source-interface mgmt0
ntp source-interface mgmt0
```

section 判定には元 file のインデントまたは `!` 境界を使用します。protected section の配下をすべて
インデントなしにした file は安全に範囲を確定できないため、投入前に validation error となります。元の
階層を保持するか、section 間へ `!` を残してください。

## 3. 投入前表示

除外対象がある場合、対象確認 prompt より前に category、行数、sanitized command を表示します。

```text
=== PUSH CONFIG CONNECTION SAFETY ===
- leaf01: excluded=9
  - current_login_user: lines=1 command=username admin <redacted>
  - management_vrf: lines=2 command=vrf context management
  - management_interface: lines=3 command=interface mgmt0
  - line_vty: lines=3 command=line vty
Use --force only when these commands must be included.
=======================================
```

`username` の password、secret、hash は端末と log に表示しません。除外後に投入可能な command がない
host は mutation 対象から外します。

## 4. `--force` で接続保護 filter を解除

接続経路の変更を意図的に同じ session で投入する場合だけ、`--force` を指定します。

```bash
alred push-config-dir \
  --hosts hosts.yaml \
  --input-dir raw/config \
  --file-suffix _run.txt \
  --target-hosts leaf01 \
  --workers 1 \
  --force
```

`--force` は、今回の接続保護 filter と protected section の階層 validation だけを解除します。次の安全機能は
維持されます。

- connect check
- target と config file の表示
- `yes` の対話確認
- NX-OS CLI error の strict 検出
- 既存の device type 別非投入 line

`--force` では login user、management VRF、`mgmt0`、VTY の変更によって投入中または投入後の再接続が
失敗する可能性があります。到達可能な代替 user／経路と rollback 手順を確認してから使用してください。

## 5. 投入後確認と保存

投入後は別 session で対象へ再接続し、running-config と正常性を確認します。失敗した host へ同じ file を
無条件で再送しないでください。

保存が必要な場合は確認後に実行します。

```bash
alred write-memory \
  --hosts hosts.yaml \
  --target-hosts leaf01,leaf02
```

投入と同時に保存する `--write-memory` も利用できますが、management／AAA を含む config では、再接続確認後に
`write-memory` を分けて実行することを推奨します。

## 6. Containerlab での利用

推奨の Containerlab 経路は `clab-transform-config` と `clab-apply-config` です。`clab-apply-config` は変換済み
Manifest、risk scan、post-apply credential での再接続、semantic verification を使用するため、この direct
`push-config-dir` filter を内部で重ねません。詳細は
[NX-OS Boot and Config Push](../containerlab/05_NXOS_BOOT_AND_CONFIG_PUSH.md)を参照してください。
