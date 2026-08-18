# Config Transformation

## 1. 必須 option と入力 mode

`clab-transform-config` に常時必須の option はない。入力 mode ごとの必要条件は次のとおりである。

| 入力 mode | 必要な option | 条件 |
|---|---|---|
| Evidence Package | `--evidence-package <imported-package-directory>` | Package を入力にする場合の mode 選択に必要 |
| Evidence Package／`verbatim` | `--evidence-package` と `--acknowledge-sensitive-config` | 原文 config を含む Package だけで必要 |
| 既存 file | なし | `./hosts.yaml` と `raw/config/<hostname>_run.txt` を既定入力に使用 |

`--hosts`、`--input`、`--lab-parameters`、出力先 option などは任意である。既定 path 以外を使う場合または
変換 policy を明示する場合に指定する。

## 2. 推奨: Evidence Package から変換

商用環境と隔離 lab を分離する標準経路では、検証済み import directory を Manifest 入力として使用する。

```bash
alred clab-transform-config \
  --evidence-package imported-evidence/<package-id>
```

`--lab-parameters` を省略すると built-in safety policy を使用する。既定の出力は `hosts.lab.yaml`、
`raw/labconfig/`、`raw/lab-transform-manifest.yaml` である。これらを変更する場合だけ
`--output-hosts`、`--output-dir`、`--manifest-output` を指定する。

生成する `hosts.lab.yaml` は `prepare-hosts` と同じ device mapping で `os_type`、
`ansible_network_os`、`ansible_connection`、`netmiko_device_type` を補完する。source inventory に
明示値がある場合はその値を保持する。

directory を再帰探索して config を推測せず、Package Manifest の `command_id: running_config`、device、path、export hash を
解決する。`sanitized` は acknowledgement 不要、`verbatim` は `--acknowledge-sensitive-config` が必要である。旧 Package でも
現在の Secret Scan を通過しなければ変換へ進まない。

変換後は `LabTransformManifest` の device 数、missing source、source／output hash、warning、risk finding を確認する。
Evidence Package 経路は missing running config、inventory との device 集合不一致、hash 不一致を fail closed とする。

## 3. 既存互換: raw directory から変換

```bash
alred clab-transform-config
```

既定で `./hosts.yaml` と `raw/config/<hostname>_run.txt` を読み、file suffix は `_run.txt` とする。別 path は
`--hosts`、`--input`、`--file-suffix` で指定する。management subnet 変換、node 対応、正規化 mapping が必要な場合は
`--clab-env`、`--node-map`、`--mappings` をそれぞれ指定する。

主な変換対象はmanagement address、hostname、同名VDC、vPC keepalive、interface description、NX-OS
9000v向けinterface設定である。その他のsection順と未対象lineは可能な限り保持する。

`--input raw`は同一環境内の既存 file互換経路である。source configがない hostをwarningでskipする動作と、
Evidence Package経路の fail-closed動作を混同しない。

### `--clab-env` の内容

`--clab-env` には Containerlab topology 形式の YAML を指定する。この command が参照する field は
`mgmt.ipv4-subnet` だけであり、source inventory と `interface mgmt0` の address を、host 部を維持したまま
lab 用 subnet へ変換する。`topology.kinds`、image、bind mount など、同じ YAML のその他の field は
`clab-transform-config` の出力へ merge しない。

```yaml
mgmt:
  network: clab-mgmt
  ipv4-subnet: 172.20.20.0/24
```

未指定時は `./clab_merge.yaml` が存在すれば使用し、存在しなければ subnet 変換を行わない。明示指定した
file の欠落、不正な YAML、`mgmt.ipv4-subnet` の不正値、変換後 address の重複は error とする。

## 4. Lab user

credentialが完全に解決できる場合、同名NX-OS userをlab用設定へ置換する。生成される boot後投入用 configには平文passwordが
含まれ得る。

既存 image の default user を利用して全 user を削除する場合は `--delete-username` を指定する。商用 VTY access class を
lab へ持ち込まない場合は `--delete-access-class` を指定する。どちらも任意の互換 option である。

変換結果をsample、fixture、Gitへ追加しない。lab利用後の保存・破棄手順を環境側で決める。

## 5. Node map

```csv
source_hostname,source_mgmt_ip,target_hostname,target_mgmt_ip
leaf01,192.0.2.11,lab-leaf01,172.20.20.11
leaf02,192.0.2.12,lab-leaf02,172.20.20.12
```

mappingはinventory key、`ansible_host`、出力filename、config hostname、description、management address、
vPC keepaliveへ一貫して適用される。重複hostname／IPや不一致addressはerrorとして扱う。

## 6. Default safety policy

parameter未指定時もbuilt-in safety policyを適用する。production user、AAA、
SNMP、NTP、logging、DNS、certificate／key、management access class を既定で除去する。lab userは解決可能な
lab credentialまたは明示 parameterがある場合だけ生成し、production credentialへ fallbackしない。
`--delete-username`と`--delete-access-class`は互換optionとして維持する。

`replace`は既存設定を1件ずつ置換せず、対象カテゴリをすべて除去して、parameter で指定した lab-local 設定集合を生成する。
例えば既存 NTP server が2台で replacement が1台なら、変換結果には replacement の1台だけを残す。詳細仕様と
設計段階の sample は[Containerlab Workflow Design](../../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md#562-replaceの共通規則)と
[`lab-transform-parameters.default.example.yaml`](../../../alred/sample_configs/lab-transform-parameters.default.example.yaml)を参照する。

既存の安全な NTP option を維持して address だけを変更する場合、`source_address`は任意である。省略時は既存行と
replacement を出現順で対応し、`prefer`、`use-vrf`、`minpoll`、`maxpoll`だけを継承する。replacement が少ない場合は余った
既存 server を削除し、多い場合は error とする。追加には`inject`を明示する。`source_address`は特定行へ明示対応するときだけ
使用し、authentication key や未知 option は自動継承しない。実際の config と parameter 例は
[NX-OS NTP server の address 置換](../../design/containerlab/CONTAINERLAB_WORKFLOW_DESIGN.md#5621-nx-os-ntp-server-の-address-置換)を参照する。

Evidence Package の型付き`mask`で address が失われていても、command 構造、出現順、安全な option が残っていれば同じ置換を
行える。placeholder は機器へ投入しない。必要な構造が完全に除外されていても parameter から完全生成できる場合は生成し、
必須情報を補完できない場合だけ`LAB_TRANSFORM_INCOMPLETE_SOURCE`で停止する。

parameter loader、default remove policy、NTP `remove`／`replace`／`inject`、logging／DNS／AAA／SNMP／management
access class の`replace`、複数lab user、bootstrap `preserve`／`replace-credential`、Manifest出力は実装済みである。
`remove-after-primary-ready`の削除処理は`clab-apply-config`が担当する。非NX-OS adapterは未実装であり、指定時は
fail closedとする。

AAA、SNMPなどの秘密値はparameterへ直接記載せず、`credential_ref`から環境変数を実行時に解決する。`replace`の入力例は
[`lab-transform-parameters.default.example.yaml`](../../../alred/sample_configs/lab-transform-parameters.default.example.yaml)を
参照する。

## 7. 保持する非 secret command

sanitizerと変換処理は credential-bearing contextへ positive matchした commandだけを除去する。routing policyまたは
password policyを keywordだけで secretと判定しない。少なくとも次は原文を保持する。

- `send-community`、`send-community extended`、`send-community both`
- `match community`、`set community`、`set extcommunity`、community list
- `password strength-check`、`no password strength-check`
- `password secure-mode`、`no password secure-mode`
- `password required`、`no password required`

一方、`username <name> passphrase lifetime ...`は credential commandを除去した後に単独で残すと投入失敗になるため、同じ
user credential groupとして除去する。変換後 configで上記の非 secret commandが欠落する場合は、import処理ではなく
Package作成時の sanitizer ruleと`redaction_count`を確認する。
