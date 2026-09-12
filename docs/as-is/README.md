# As-Is Implementation Notes

## 1. 目的

現行コード、CLI help、README、CONFIG、テスト、生成物から観測した既存動作を、正式な
設計書へ反映する前の確認資料として記録する。

本ディレクトリは暫定的な解析領域であり、仕様の正本ではない。現在有効な正式仕様は
[設計書一覧](../design/README.md)、設計書化の進捗は
[Existing Feature Documentation Status](../implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
を参照する。

## 2. As-Is記録の扱い

As-Is記録には、次を明確に分離して記載する。

- `Observed`: コード、テスト、CLI出力、生成物から直接確認できた事実
- `Documented`: READMEやCONFIGに記載されているが、コードとの一致を未確認の内容
- `Inferred`: 複数の証拠から推測した内容
- `Unknown`: 意図、例外条件、互換性などを確認できていない内容

`Inferred`を正式仕様として扱ってはならない。実装にバグまたは偶然の挙動が疑われる場合は、
そのまま期待仕様へ昇格せず、設計判断が必要な差異として記録する。

## 3. 解析から正式設計まで

```text
コード・CLI・文書・テスト・生成物を確認
    ↓
As-Is記録（Observed / Documented / Inferred / Unknown）
    ↓
現行動作が意図した仕様かレビュー
    ↓
設計書またはADRへ統合
    ↓
不足するテスト・実装・利用者文書を同期
    ↓
As-Is記録をIntegratedとして完了
```

正式設計へ統合した後は、As-Is記録に統合先と日付を記載する。As-Is側へ独立した仕様を
残さず、内容が重複する場合は要約と正本へのリンクだけを保持する。

## 4. As-Is文書テンプレート

```text
# <機能名> As-Is

- Status: Analyzing
- Last reviewed: YYYY-MM-DD
- Scope: <対象module / CLI>

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/example.py` | ... |
| Test | `tests/test_example.py` | ... |
| CLI | `alred example --help` | ... |

## Observed behavior

## Documented but not verified

## Inferred behavior

## Unknowns and conflicts

## Recommended design disposition

## Integration

- Design document: TBD
- ADR: Not required / TBD
- Integrated date: -
```

## 5. 禁止事項

- 解析していない挙動を推測で補完しない。
- テストが成功することだけを、利用者に保証された仕様の根拠にしない。
- secretや実機の認証情報をAs-Is文書またはfixtureへ保存しない。
- As-IsとTo-Beを同じ記述で混在させない。
- 正式設計へ統合済みの仕様を、本ディレクトリで別途変更しない。

## 6. 現在のAs-Is記録

- [NTP Health Check 実装レビュー](./NTP_HEALTH_CHECK_REVIEW.md)（修正前の観測記録、設計へ統合・修正済み）
- [CLI Framework](./CLI_FRAMEWORK_AS_IS.md)
- [CLI, Configuration, and Resources](./CLI_CONFIGURATION_AND_RESOURCES_AS_IS.md)
- [Collect Output](./COLLECT_OUTPUT_AS_IS.md)
- [Inventory, Credentials, and Transport](./INVENTORY_CREDENTIALS_AND_TRANSPORT_AS_IS.md)
- [VNI Config Renderer](./VNI_CONFIG_RENDERER_AS_IS.md)
- [VNI Map](./VNI_MAP_AS_IS.md)
- [Config Push / Save](./PUSH_CONFIG_AS_IS.md)
- [Role Detection and Resolution](./ROLE_RESOLUTION_AS_IS.md)
- [Containerlab Workflow](./CONTAINERLAB_WORKFLOW_AS_IS.md)
- [Topology and Rendering](./TOPOLOGY_AND_RENDERING_AS_IS.md)
- [Development and Packaging](./DEVELOPMENT_AND_PACKAGING_AS_IS.md)
