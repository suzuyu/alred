# NX-OS Boot and Config Push

## 1. 目的と現在の状態

NX-OS 9000v は、Containerlab の `topology.kinds.cisco_n9kv.startup-config` を使用すると、boot 中の config 投入で
停止する場合がある。このため、alred が生成する topology の既定値では `startup-config` を出力せず、9000v の
boot 完了後に `clab-apply-config` で設定を投入する。`push-config-dir` は既存 file 互換経路として維持する。

この既定値は実装済みである。`clab-merge` または `clab-lab-profile` で明示した場合を除き、`generate-clab` は
`cisco_n9kv` kind へ `startup-config` を自動設定しない。

`clab-merge` または `clab-lab-profile` で `startup-config` を明示した場合は、boot-time 投入を明示的に選択したものとする。

## 2. Deploy 前確認

```bash
grep -n "startup-config" output/topology.clab.yaml
```

comment ではない`startup-config:`が`cisco_n9kv` kind または node に残っていないことを確認する。Linux や
Kind cluster など、NX-OS 9000v 以外の startup artifact は対象外である。

## 3. 9000v を起動する

```bash
containerlab deploy -t output/topology.clab.yaml
containerlab inspect -t output/topology.clab.yaml
```

Containerlab CLI は alred の管理外である。全 9000v node が起動し、management address へ接続可能になるまで
config を投入しない。

## 4. Bootstrap credential

boot 前には`raw/labconfig/`内で定義した lab user がまだ存在しない。最初の config push には、使用 image の
bootstrap credential または lab 専用に準備した credential を使用する。production credential へ fallback しない。

初期仕様では Containerlab の bootstrap `admin:admin`を default で保持し、production source config に含まれる user の
除去とは分離する。`lab-transform-parameters.yaml`で`lab_users`を指定した場合も、明示的に
`bootstrap_user.action: remove-after-primary-ready`を指定しない限り bootstrap user を削除しない。保持は risk scan と
verification に`WARN`として表示される。

bootstrap `admin`の credential を変更する場合は`bootstrap_user.action: replace-credential`と`password_ref`を明示する。
変更前に connectivity risk の確認があり、変更後は session を閉じて新 credential で再接続する。再接続できない場合は失敗し、
save しない。`bootstrap_user.action: preserve`と同時に`lab_users`へ同名の`admin`を定義することはできない。

`hosts.lab.yaml`の management address と、`clab_credentials.yaml`または対話入力の credential が、起動済み lab
node を参照していることを確認する。

## 5. Config を投入する

標準経路では `clab-transform-config` が生成した Manifest を使用する。`clab-apply-config` は topology の `startup-delay` と
Docker health を確認してから、strict CLI error 判定を使用して投入する。

`--topology`には実際に `containerlab deploy` で使用した Topology を指定する。生成済み Topology と起動済み lab の
node 名が同じでも、`name`が異なる別 lab へ自動的に読み替えない。

```bash
alred clab-apply-config \
  --topology output/topology.clab.yaml \
  --hosts hosts.lab.yaml \
  --lab-transform-manifest raw/lab-transform-manifest.yaml \
  --workers 1 \
  --fail-fast
```

`clab-apply-config` は `output/clab-apply-config/<attempt-id>/` へ、readiness、bootstrap 処理、秘密値を除いた running config、
semantic diff、verification、save 結果を保存する。`--write-memory` を指定した場合も、`VERIFIED` の node だけを保存する。
`VERIFIED_WITH_DIFF` を保存する場合は差分確認後に `yes` と入力するか、automation で `--accept-verification-diff` を明示する。
必須 invariant の失敗はこの option で許可できない。

投入前には`risk-scan.yaml`を生成する。`WARN`がある場合は通常の投入対象確認とは別に`yes`が必要であり、automationでは
`--accept-connectivity-risk`を指定する。active mask、private key、未検証management addressなどの`BLOCK`はoptionでは
回避できない。command単位resultは`command-results/<hostname>.yaml`へ保存されるが、password、AAA key、SNMP communityと
response内のecho値は`<redacted>`へ置換される。

起動済み lab へ実行した場合は、初回の `containerlab inspect` で全対象 node が `healthy`なら待機せず投入前処理へ進む。
起動途中の場合は node 状態、pending node、次回確認までの秒数を標準出力と`logs/clab-apply-config.log`へ出力する。
指定 Topology の lab 名が存在せず、同じ node 群を持つ別名の稼働 lab がある場合は、誤投入防止のため即時停止する。

`--fail-fast` を指定すると、最初の host failure 後に未着手 host を開始しない。`--workers 1` との組み合わせでは次の host へ
進まない。CLI error は `host`、`line=<投入行番号>/<総投入行数>`、秘密値を除去した `command`、`error` の簡潔な log として
表示し、Python Traceback は表示しない。失敗直前に正常処理された最大 5 command も `PUSH CLI CONTEXT` として表示する。
原因調査には attempt の `command-results/<hostname>.yaml` を使用する。

調査目的で非推奨の `--ignore-all-cli-errors` を使用した場合も、各 `IGNORED_ERROR` の直前に正常処理された最大 5 command と
該当 command を `WARNING` で表示する。`IGNORED_ERROR` は host failure ではないため、`--fail-fast` では停止しない。

NX-OS 9000v の bootstrap SSH key が既に存在し、`ssh key rsa <bits>`が既存 key errorを返した場合だけ、
`NXOS_CLAB_SSH_KEY_ALREADY_EXISTS`として`WARN`で継続する。変換済み config からこの行は削除しない。異なる SSH key error、
`force`付き command、汎用`push-config`／`push-config-dir`には既定適用しない。command result の`allow_rule_id`と、投入後の
SSH再接続・verificationを確認する。

成功後は`output/clab-apply-config/current.json`が最新成功attemptを指す。同じtopology／Manifestで再実行すると、live configが
`VERIFIED`のnodeは再投入を省略し、差分または取得失敗のnodeだけを対象とする。全nodeへ再投入する場合は
`--reapply-all`を指定する。

credentialを指定せず、`clab_credentials.yaml`と環境変数もない場合、初期NX-OS実装はbootstrap `admin:admin`を使用する。
production credentialへfallbackしない。

既存file互換経路では、まず対象hostと投入fileの対応を確認する。

```bash
find raw/labconfig -maxdepth 1 -type f -name '*_run.txt' -print
```

```bash
alred push-config-dir \
  --hosts hosts.lab.yaml \
  --credentials clab_credentials.yaml \
  --input-dir raw/labconfig \
  --file-suffix _run.txt \
  --workers 1
```

`push-config-dir`は mutation command であり、対象確認 prompt に`yes`と入力した場合だけ開始する。初回は
`--workers 1`で serial に投入し、management／AAA／VTY変更後も接続を維持できることを確認する。
direct command の既定接続保護 filter と `--force` は
[push-config-dir Guide](../network-ops/10_PUSH_CONFIG_DIR.md)を参照する。推奨経路の `clab-apply-config` は
変換済み Manifest、risk scan、再接続、semantic verification を使用し、この direct filter を内部で重ねない。

永続保存も同時に行う場合は`--write-memory`を指定できる。ただし、投入結果と到達性を確認する前に保存しない運用を
推奨する。

## 6. 投入後確認

```bash
alred check-clab-startup-config \
  --hosts hosts.lab.yaml \
  --credentials clab_credentials.yaml \
  --startup-dir raw/labconfig \
  --file-suffix _run.txt \
  --output-dir output/check-clab-startup-config \
  --workers 1
```

`push-config-dir`と`clab-apply-config`はNX-OS CLI error textを既定で検出する。`clab-apply-config`はManifestの
post-apply username／`password_ref`を使用して投入成功hostへ再接続し、必須semantic invariantと参考差分を判定する。
`remove-after-primary-ready`ではprimary userの再接続成功後だけbootstrap `admin`を削除し、もう一度再接続する。失敗時は
`APPLY_FAILED`としてsaveしない。従来の`check-clab-startup-config`は、独立したread-only確認が必要な場合に引き続き利用できる。
