# Overlay Configuration Quick Start

この章では、宣言済み `OverlayChangeSet` から NX-OS の Overlay（VNI／VRF／SVI）設定を生成し、
plan、approval、apply、after 検証、save までを 1 つの Operation で管理するモデルケースを示します。

本手順は設定を変更します。最初に lab で実行し、対象 model、NX-OS release、role、Capability が
`APPLY_VERIFIED` であることを確認してください。詳細仕様は
[Overlay Change Management Design](../../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)を参照します。

## 1. モデルケース

同梱 sample は、Single-site Fabric の 2 組の vPC Leaf pair に、既存 VRF `tenant1-vpc1`／
L3VNI 19001 を利用する L2VNI 10100 と Gateway SVI を追加します。pair 1 は VLAN 100、pair 2 は
VLAN 10 です。実環境では sample の hostname、VNI、VLAN、VRF、IP address、BGP 関連値を
そのまま使用しないでください。sample の before／after Health Check と config の関係は
[Overlay ChangeSet sample](./examples/overlay-changeset/README.md)で確認できます。

```bash
mkdir -p changes/CHG-2026-00123
cp docs/manual/network-ops/examples/overlay-changeset/desired-changes.yaml \
  changes/CHG-2026-00123/desired-changes.yaml
cp docs/manual/network-ops/examples/overlay-changeset/device-groups.fabric.yaml \
  changes/CHG-2026-00123/device-groups.fabric.yaml
```

次の 2 file を対象環境に合わせます。同梱 sample の `metadata.change_id` は本手順と同じ
`CHG-2026-00123` ですが、別の change ID を使用する場合は directory 名、ChangeSet、以降の command を
すべて同じ値へ変更します。

- `changes/CHG-2026-00123/desired-changes.yaml`
- `changes/CHG-2026-00123/device-groups.fabric.yaml`

入力項目と validation は
[Overlay ChangeSet Guide](./07_OVERLAY_CHANGESET_GUIDE.md)を参照してください。

## 2. 機器アクセスなしで事前 plan を確認（任意）

対象 device をすべて含む過去の正常な最終状態がある場合、機器へ接続せずに config と競合候補を
確認できます。参照できるのは正常完了した `after`、または検証済み `rollback` です。作業前の
`before` だけを持つ Operation、収集中断などで必須 metadata／成果物がない Operation は参照しません。
該当する正常な最終状態がない場合は本節をスキップし、次の `before` 収集へ進みます。

この preparation plan は事前レビュー専用であり、approval／apply には使用できません。

```bash
alred overlay-change prepare-plan \
  --change-set changes/CHG-2026-00123/desired-changes.yaml \
  --reference-state latest-known-good
```

自動選択は不完全または不適格な候補をスキップし、対象 device をすべて含む候補のうち Snapshot の
`created_at` が最新のものを選択します。候補がない場合は `REFERENCE_STATE_NOT_FOUND` で停止します。
`--allow-reference-state-warn` は正常完了した Overlay terminal Operation の `WARN` を参照元として明示的に
許可する option です。`PASS` の参照元だけを使用する場合は省略します。
standalone Health Check の `WARN` は自動選択せず、詳細手順で `--reference-operation-id` と同 option を
指定した場合だけ利用できます。
特定の Operation を監査上明示したい場合は、詳細手順の
[過去の正常状態で準備用 plan を作成](./07_OVERLAY_CHANGESET_GUIDE.md#11-過去の正常状態で準備用planを作成)を
参照してください。

## 3. before を収集

`network-baseline-nxos` と `nxos-overlay` を同じ before で収集します。

```bash
alred health-check before \
  --collect \
  --hosts hosts.yaml \
  --change-id CHG-2026-00123 \
  --profile network-baseline-nxos \
  --profile nxos-overlay \
  --logging-days 1 \
  --ask-pass
```

inventory の指定誤りなどで直接収集を `Ctrl-C` で中断した場合、該当 attempt は `CANCELLED` として
保持されます。inventory を修正し、同じ change ID、profile、入力方式で同じ command を再実行すると、
新しい attempt で収集を開始します。`OPERATION_LOCKED` の場合は別 process が実行中でないことを確認し、
lock を自動削除せず [Troubleshooting](./05_TROUBLESHOOTING.md)を参照してください。

Checklist、VNI map、対象 host、既存異常を確認します。`FAIL`／`UNKNOWN` の場合は plan へ進みません。
`WARN` は内容と Operation Gate の判断を記録します。

端末 summary に表示された Operation directory へ、レビュー済み ChangeSet と group file を固定します。
次の `<operation-directory>` は実際に表示された path へ置き換えてください。

```bash
cp changes/CHG-2026-00123/desired-changes.yaml \
  <operation-directory>/desired-changes.yaml
cp changes/CHG-2026-00123/device-groups.fabric.yaml \
  <operation-directory>/device-groups.fabric.yaml
```

## 4. 通常 plan を生成してレビュー

```bash
alred overlay-change plan \
  --change-set <operation-directory>/desired-changes.yaml \
  --hosts hosts.yaml
```

少なくとも次をレビューします。

1. 対象 device と resolved device group。
2. `conflict-report.md` と Capability 判定。
3. `generated-config/` の forward config。
4. `rollback-config/` の rollback config と削除順序。
5. VNI、VLAN、VRF、SVI address、BGP AS、route-map。
6. ChangeSet、group、resolved target、plan、config の hash。

`PLAN_CONFLICT` で停止した場合、端末に `Conflict report: <path>/conflict-report.md` が表示されます。
表示された Markdown を開き、device、resource、code、message を確認してから実機状態または ChangeSet を
修正し、before／plan を再実行します。

修正が必要な場合は生成物を直接編集せず、ChangeSet を修正して新しい Operation で before／plan を
再生成します。

## 5. plan を承認して apply

```bash
alred overlay-change approve \
  --change-id CHG-2026-00123
```

表示された artifact、hash、対象 device、`save_on_success`、rollback policy を確認し、対話 prompt で
承認します。続いて apply を実行します。

```bash
alred overlay-change apply \
  --change-id CHG-2026-00123 \
  --ask-pass
```

apply は serial 1、retry なしで実行し、この時点では startup-config へ保存しません。失敗時は再送せず、
`apply/execution.json` と device 別 command log から成功範囲を確認します。

## 6. after と Overlay を検証

```bash
alred health-check after \
  --change-id CHG-2026-00123 \
  --ask-pass
```

```bash
alred overlay-check evaluate \
  --change-id CHG-2026-00123
```

共通 Health Check、before／after 差分、VNI map、Overlay 評価が意図した結果であることを確認します。
共通 Health Check の `WARN` は内容をレビューしますが、Overlay が `VERIFIED`／`OBSERVED_HEALTHY` であれば
save へ進めます。`FAIL`／`UNKNOWN`／`NOT_APPLICABLE`／`PLAN_ERROR` または未収束の場合は save せず、
rollback の要否を判断します。

## 7. 明示的に保存

after と Overlay 評価が成功し、Approval Record が保存を許可している場合だけ実行します。

```bash
alred overlay-change save \
  --change-id CHG-2026-00123 \
  --ask-pass
```

save 前には live running-config と after Snapshot が再検証されます。

全対象が `NO_CHANGE` の場合、save は承認と after gate だけを検証する no-op として完了し、機器へ接続しません。

## 8. 失敗時と詳細手順

自動 rollback は行いません。apply 失敗、after 非 PASS、保存後 rollback を含む詳細手順は
[alred Overlay Change Apply](./08_ALRED_OVERLAY_CHANGE_APPLY.md)を参照してください。
rollback の実行方法は、同文書の
[13. 手動 rollback](./08_ALRED_OVERLAY_CHANGE_APPLY.md#13-手動rollback)を参照してください。

- ChangeSet schema と sample: [Overlay ChangeSet Guide](./07_OVERLAY_CHANGESET_GUIDE.md)
- Overlay 収集と VNI map: [NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)
- 対応範囲: [NX-OS Capability and Fixture Matrix](../../design/network-ops/NXOS_CAPABILITY_AND_FIXTURE_MATRIX.md)
