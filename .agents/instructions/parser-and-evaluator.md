# Parser and Evaluator Instructions

## Scope

config、show command output、外部 transcript、JSON sidecarを読み取るparser、Canonical Snapshotへの
正規化、Health／Topology／operation evaluator、比較判定を設計・変更するときに適用する。

## Detailed design requirements

責務を持つ正本の設計書へ、少なくとも次を記録してから実装する。

- 対象platform、OS release、command ID、実行command、text／JSONなどの入力形式
- 読み取るconfig sectionまたはshow outputのheading、row、column、labelなどの識別anchor
- anchorから抽出するfield、型、単位、大小文字、interface名、address／prefixなどの正規化規則
- 同じ値を複数箇所から取得できる場合の優先順位、fallback、source provenance
- 対象機能が未設定の場合と、必須outputの欠落、空、timeout、unsupported、parser errorの区別
- 曖昧なrow、重複、未知値、release差を推測で補わず、`UNKNOWN`または明示errorにする条件
- evaluatorが参照するSnapshot field、計算式、閾値の境界を含む`PASS`／`WARN`／`FAIL`／`UNKNOWN`／
  `NOT_APPLICABLE`の条件
- before／after比較時のresource identity、追加、消失、counter reset、regression、pre-existingの扱い
- resultからraw file、command、該当sectionへ遡れるevidenceとparser version
- 正常系、境界値、欠損、破損、未知値、複数release差を確認するsanitized fixtureとtest

実装内のregular expressionや偶然のcolumn位置だけを仕様の正本にしない。設計書には秘密情報や実在する
hostname／管理addressを含めず、入力例は架空値またはsanitized fixtureを使用する。

## Implementation rules

- collector、parser、normalizer、evaluator、reportの責務を分離する。
- parserは観測値とprovenanceを返し、運用上の合否や閾値を埋め込まない。
- evaluatorはraw textを再解析せず、schema検証済みのCanonical Snapshotを参照する。
- 単位変換と正規化は一度だけ行い、raw値、正規化値、使用単位を追跡可能にする。
- parserが認識できない入力を空集合、0、正常状態として返さない。
- optional機能の未設定は`NOT_APPLICABLE`、取得または解析不能は`UNKNOWN`として区別する。
- profileのplatform scope外ではcommandとcheckを実行せず、未実行理由を成果物へ残す。
- 集合またはrangeを扱う判定では、resource単位の対応関係を保存し、集計件数だけで正常性を推測しない。
- counter差分ではreset、wrap、取得間隔を検討し、安全に判定できない場合は`UNKNOWN`とする。
- parserまたは判定意味を変えた場合はparser version、profile version、schema互換性への影響を確認する。

## Verification

- fixtureは実機rawを直接commitせず、secret、hostname、管理address、serial等をsanitizationする。
- parser testでは抽出値だけでなく、欠損anchor、空output、CLI error、未知row、境界値を確認する。
- evaluator testでは閾値の直前／一致／直後、単体判定、before／after regressionを確認する。
- command、Snapshot field、判定条件、fixture、実装状態の対応を設計書と`IMPLEMENTATION_STATUS.md`で確認する。
