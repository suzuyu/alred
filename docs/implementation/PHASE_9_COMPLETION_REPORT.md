# Phase 9 Completion Report

## 1. 完了判定

Phase 9は2026-07-30に完了した。allowlist、Collection Manifest固定raw、redaction、
pseudonymization、secret scan、AI prompt、deterministic archive、inspect、verify、
device/phase分割、device filter、site固有policyを実装した。

## 2. 実装済みCLI

```bash
alred support-bundle create \
  --change-id CHG-2026-00123 \
  --phase after \
  --split device \
  --devices leaf01,leaf02 \
  --redact-profile support-redaction.yaml \
  --symptom "after health check failed" \
  --question "beforeからのregressionを整理してください" \
  --operations-root operations \
  --output support-bundles

alred support-bundle inspect \
  --bundle support-bundles/CHG-2026-00123-after.tar.gz

alred support-bundle verify \
  --manifest support-bundles/CHG-2026-00123-after.manifest.yaml
```

## 3. 安全性

- operation directory全体を直接tar化しない
- phase別allowlistとCollection Manifest参照内のregular text fileだけを選ぶ
- symlink、path traversal、special/non-file memberを拒否
- `.env`、credential名、private key名、dot fileを含めない
- redaction前原本を変更しない
- redaction後にsecret scanし、残存時はarchive生成を停止
- hostname/IP/VRF/home pathをbundleと全part内で一貫した仮名へ置換
- pseudonym対応表やsaltを保存しない
- archiveはredactedだが非暗号化であることをREADMEと端末へ表示

## 4. 成果物

```text
<change-id>-<phase>.tar.gz
<change-id>-<phase>.manifest.yaml
<change-id>-<phase>.sha256
<change-id>-<phase>-prompt.md
```

archive内にはREADME、prompt、manifest、allowlisted/redacted artifact、内部checksumを格納する。

## 5. 完了した追加範囲

- phase/device splitとmachine-readable part index
- device filterと未知deviceのfail-closed
- site固有redaction policy schema/validation
- generated/rollback configとraw loggingのinclude toggle
- operation内外raw参照のsource hash、line range検証
- split part間で共通のhostname/IP/VRF pseudonym
- device分割、対象外device除外、100 MiB超過のpytest

## 6. 検証

```text
uv run --frozen pytest tests/test_support_bundle_phase9.py tests/test_operation_schema.py -q
17 passed

uv run --frozen pytest -m "not device" -q
153 passed
```

実機や外部サービスへの接続は使用していない。
