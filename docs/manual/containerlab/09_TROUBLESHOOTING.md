# Troubleshooting

## 1. Raw が不足する

```bash
find raw/lldp raw/config -maxdepth 2 -type f -print
```

Evidence Package 経路では、先に選択した Operation attempt の `collection-manifest.yaml`、command status、file path、
line range、SHA-256 を確認する。既存 Operation を再利用する Pattern では不足 file を別 attempt から補完せず、必要なら
Pattern A として新しい `health-check before --purpose inspection --collect` を実行する。

既存互換の `collect-clab` 経路だけは、対象 host、policy、connect check、credential、transport を確認して再実行する。
成功済み file と失敗 retry を同一世代と推測しない。

## 2. Candidateしか生成されない

LLDPが片方向だけ、description ruleに一致しない、hostname／interface mappingが不足している可能性がある。

```bash
alred normalize-links \
  --hosts hosts.yaml \
  --input raw \
  --mappings mappings.yaml \
  --description-rules description_rules.yaml \
  --output-confirmed output/links_confirmed.csv \
  --output-candidates output/links_candidates.csv \
  --verbose
```

candidate CSVの`evidence`と`warning`を確認する。

## 3. Boot 後投入用 config が生成されない

Evidence Package 経路では、Package Manifest の `command_id: running_config`、device、path、export hash、inventory との
device 集合を確認する。不足または不一致は fail closed となる。

既存 file互換経路では`raw/config/<hostname>_run.txt`または対応JSON、inventoryのhostname、`--file-suffix`、node mapを
確認する。source不足はwarningでskipされても`hosts.lab.yaml`へnodeが残るため、Manifest経路と混同しない。

## 4. `init-clab`が停止する

`output/init_clab_validation.md`で、未知node、自己link、endpoint重複、management IP重複、subnet外addressを
確認する。`--validate-only`でもreportとnormalized CSVは生成される。

## 5. 起動後にconfig差分がある

imageが非対応commandを削除した、起動時に動的lineを追加した、startup configがbindされていない、node名／
suffixが不一致などを確認する。`check-clab-startup-config`は差分を修正しない。

## 6. NX-OS 9000v が boot 中に停止する

`topology.kinds.cisco_n9kv.startup-config`または node 個別の`startup-config`が有効になっていないか確認する。
現行 `generate-clab` は、merge／lab profile で明示されない限り NX-OS 9000v の `startup-config` を生成しない。
生成 topology へ field が残る場合は、どの merge 入力が追加したかを確認する。9000v を config なしで起動した後、
[NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md)に従って `clab-apply-config` で投入する。

## 7. `clab-apply-config` が readiness 待機から進まない

`--topology`に指定した Topology の`name`と、実際に起動している lab 名が一致することを確認する。

```bash
grep '^name:' output/topology.clab.yaml
containerlab inspect --all --format json
```

node 名が同じでも、別 lab 名の container へ自動的に投入しない。既存 lab へ投入する場合は、その lab を実際に deploy した
Topology file を`--topology`へ指定する。現行実装は同じ node 群を持つ稼働中の別名 lab を検出すると、候補 lab 名と
Topology path を表示して即時停止する。

起動途中の場合は、標準出力と`logs/clab-apply-config.log`の`CLAB READINESS`行で、node ごとの runtime／health、
pending node、次回 poll を確認する。`containerlab inspect`を利用できない場合は Docker inspect fallback の理由も記録する。

## 8. Evidence Package が Secret Scan で停止する

`evidence-package inspect`／`verify` の status、rule ID、artifact ID、path、line 位置を確認する。一致値や周辺の秘密値を
terminal、issue、chat へ貼り付けない。旧 Package で `secret_scan_declared: false` の場合は、可能なら source Collection
Manifest から現行 schema で再作成する。

`send-community`、`match community`、`set community`、`set extcommunity`、community list、
`no password strength-check` などが欠落する場合は、非 secret command を手動追記して Package を改変せず、sanitizer rule を
修正して source から再作成する。

## 9. Evidence Package の自動選択が古い legacy directory で停止する

現行実装は、`health/before/current.json` がない raw-only legacy directory を自動選択候補からスキップする。
`current.json` があるのに `metadata.yaml`、attempt、Snapshot、Collection Manifest が不整合な場合は、破損 source を
見逃さないため fail closed とする。`--change-id` で不完全な directory を明示した場合も停止する。

最新版は directory 更新時刻や change ID の日時ではなく、正常公開済み `health/before/current.json` の
`completed_at` で決定する。古い停止 error が再現する場合は、使用中の binary／source がこの修正を含むか確認する。

## 10. 既知制約

- `clab-set-cmds` は全 attempt と最新成功 `current.json` を公開するが、各 canonical 出力の一括 directory switch は行わない
- `clab-set-cmds` の失敗・中断 attempt は Manifest へ保存する。再実行前に失敗 step と
  `outputs[].disposition` を確認し、以前の成功 `current.json` が指す hash と部分生成物を混在させない
- merge／optional overlay後の全link semantic validationは未実装
- startup verificationはCommon Collection Manifestへ未統合
- 非NX-OS startup config transformは正式対応外
- Portable Evidence Package の任意 phase／attempt source、support profile、開示 policy file は未実装
