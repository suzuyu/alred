## 概要

## 変更領域

- [ ] Common
- [ ] Device access and collection
- [ ] Network Operations
- [ ] Containerlab
- [ ] Topology
- [ ] Documentation

## 変更内容

## 設計への影響

- [ ] 設計変更なし
- [ ] 設計書更新済み
- [ ] ADR追加済み
- [ ] `IMPLEMENTATION_STATUS.md`更新済み

## 確認結果

- [ ] `pytest -m "not device"`
- [ ] Ruff
- [ ] CLI help／smoke test
- [ ] schema／fixture／golden test

## Binary build

- [ ] 対象外（文書・Agent指示のみ）
- [ ] PyInstaller native build成功
- [ ] binaryの`--version`／`--help`成功
- [ ] bundled sample生成成功
- [ ] glibc 2.17 build成功（packaging／release）

## 実機・lab検証

- [ ] 不要
- [ ] 未実施（理由を記載）
- [ ] Nexus 9000vで実施
- [ ] 対象hardwareで実施

対象、read-only／mutation、結果、未確認範囲:

## 互換性・rollback

## セキュリティ確認

- [ ] secret、認証情報を含まない
- [ ] `operations/`、未加工raw log、support bundleを含まない
- [ ] 生成binary、`build/`、`dist/`を含まない

## 残課題
