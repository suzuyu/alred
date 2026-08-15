# External Config to Lab

## 1. 用途

alred で収集していない NX-OS `show running-config` file を、device access なしで Containerlab 入力へ
変換する。LLDP は任意であり、ない場合は interface description だけから link を作成する。

## 2. Host 別 file を import

```bash
alred import-running-config \
  --input collected-configs \
  --input-format running-config-directory \
  --hosts hosts.yaml
```

`--output` の既定は `imported-running-config` である。file 名から host を一意に解決できない場合だけ
`--source-map` を指定する。Host 別 LLDP directory がある場合だけ `--lldp-input` を追加する。

複数 host が同じ transcript にある場合は `--input-format nxos-transcript`、従来の
`config/<hostname>_run.txt` であれば `--input-format alred-collect` を使用する。

## 3. 一括生成

```bash
alred clab-set-cmds \
  --running-config-import imported-running-config
```

import 済み Manifest が inventory、host 別 config、任意 LLDP のhashを固定する。後続 command で
`--hosts` を再指定しない。詳細に確認する場合は次の順で個別実行できる。

```bash
alred normalize-links --running-config-import imported-running-config
alred clab-transform-config --running-config-import imported-running-config
alred generate-clab --hosts hosts.lab.yaml
```

`links_candidates.csv` の片方向 description を自動採用しない。双方向 description は confirmed `low` となる。
