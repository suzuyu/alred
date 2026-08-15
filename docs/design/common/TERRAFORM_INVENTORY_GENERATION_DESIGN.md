# Terraform Inventory Generation Design

## 1. 文書の目的

`hosts.yaml`のinventory情報からTerraform NX-OS provider用`main.tf`を生成する`generate-tf`の仕様を定める。
本機能はcanonical link、LLDP、Topology render model、diagramを使用しない。`hosts.txt`から`hosts.yaml`を作る
`prepare-hosts`と同じinventory派生生成の領域に置く。

現行実装の観測根拠は[Topology and Rendering As-Is](../../as-is/TOPOLOGY_AND_RENDERING_AS_IS.md#7-terraform出力)を
参照する。

## 2. Workflowと責務

```text
hosts.txt
    ↓ prepare-hosts
hosts.yaml + roles.yaml
    ↓ generate-tf
main.tf
```

`generate-tf`は`hosts.txt`を直接parseせず、schema検証済み`hosts.yaml`を入力とする。`hosts.txt`を使用する場合は
先に`prepare-hosts`を実行する。inventory変換、role解決、HCL生成を担当し、device接続、状態収集、Topology解析、
Terraform `init`／`plan`／`apply`は行わない。

## 3. CLIと入力

現行CLIを維持する。

```text
alred generate-tf \
  --hosts <hosts.yaml> \
  [--roles <roles.yaml>] \
  [--provider-version <constraint>] \
  --output <main.tf>
```

| 入力 | 用途 |
|---|---|
| `hosts.yaml` | hostname、management address、device type |
| `roles.yaml` | legacy role group名の解決 |
| provider version | `required_providers.nxos.version`制約 |

対象は`device_type: nxos`かつmanagement IPを持つhostだけとする。その他のdevice typeとIP欠落hostは生成対象外とし、
件数と理由をlogへ記録する。hostname順、group名順、group内device順を安定させる。

## 4. 出力model

現行出力は次で構成する。

- optional `terraform.required_providers.nxos`
- legacy roleごとの`locals` device list
- hostnameを`name`、management addressを`https://<ip>`として設定
- `provider "nxos"`の`devices`へ全role groupをconcat

role名からHCL identifierを生成するときは`-`を`_`へ変換し、複数roleが同じidentifierへ衝突する場合は
validation errorとする。未知roleは既存resolverの互換値を使用し、Topologyのendpoint orderingやlink groupingを
参照しない。

## 5. Credential

credentialを生成fileへliteralで埋め込んではならない。production向け仕様はTerraform variable、environment、
または外部secret storeを参照し、secret値をstdout、log、repositoryへ残さない。

現行実装は`username = "admin"`と`password = "admin"`を固定生成しており、本要件に不一致である。修正されるまで
出力はlab用のunsafe legacy artifactとして扱い、production利用・共有・commitを禁止する。安全なcredential source、
既存出力とのmigrationは未決であり、実装変更前に設計を確定する。

## 6. Errorと再実行

- inventory／role schema不正、hostname重複、role group衝突、不正provider versionはvalidation errorとする。
- 対象NX-OS hostが0件でも構文上有効な空devicesを生成し、warningを表示する現行互換を維持する。
- 同じinventory、role、provider versionから同じbyte列を生成する。
- staging fileへ生成・validation後にatomic publishし、失敗時に以前の成功済み`main.tf`を壊さないことを目標とする。

## 7. 実装状態とtest

hosts inventory読込、NX-OS filter、legacy role group、provider version、`main.tf`生成は実装済みである。
credential literal除去、role group衝突validation、atomic publish、HCL parserによる構文検証は未実装である。

実装時はhosts.txt→hosts.yaml→main.tfの連携、NX-OS／非対象platform、IP欠落、role順、identifier衝突、provider
version、empty devices、secret literal非出力、deterministic output、partial file非公開をtestする。
