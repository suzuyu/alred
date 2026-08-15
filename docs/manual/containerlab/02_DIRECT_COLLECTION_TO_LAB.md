# Direct Collection to Lab

## 1. 位置付け

lab 生成を行う環境が対象機器へ到達できる場合の互換経路である。商用環境と隔離 lab の分離、
収集世代の固定、データ搬送の監査が難しくなるため、商用環境では Evidence Package 経路を推奨する。

## 2. 収集から一括実行

```bash
alred clab-set-cmds \
  --hosts hosts.yaml \
  --ask-pass
```

必要な場合だけ `--mappings`、`--description-rules`、`--roles`、`--sites`、`--node-map` を追加する。
pipeline の収集 step だけが device access を行い、後続は保存済み file を使用する。

既存 `raw/` を再利用する場合は `--without-collect` を追加する。異なる収集世代の file を混在させない。
