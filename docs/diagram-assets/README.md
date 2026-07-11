# README 図解パーツ

`docs/*.drawio` へ配置する独立画像パーツ。ラベル、包含関係、矢印は画像に含めず、draw.io 側で編集する。

## Google Cloud 製品アイコン

[Google Cloud 公式 Icon library](https://cloud.google.com/icons) から取得した SVG。

- Core product icons: `gcp-cloud-run.svg`、`gcp-cloud-sql.svg`、`gcp-vertex-ai.svg`
- Legacy console icons: `gcp-artifact-registry.svg`、`gcp-cloud-logging.svg`、`gcp-cloud-trace.svg`

製品名や依存関係は SVG に焼き込まず、draw.io のテキストセルとコネクタを正とする。

## 保育士イラスト

`caregiver.png` は gpt-image-2 で生成した装飾用素材。生成時は次を固定した。

- 日本の保育士 1 人とクリップボードだけを描く。
- 文字、ロゴ、製品アイコン、矢印、図表、枠、UI を描かない。
- 単色クロマキー背景で生成し、背景除去後に透過 PNG 化する。
- draw.io 上で縮小しても読める、暖色のフラットなイラストにする。

元画像の文字・配線精度には依存せず、人物パーツだけを再利用する。
