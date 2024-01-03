import argparse
import csv
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import torch
from tqdm import tqdm

from common.log import logger
from common.tts_model import Model
from config import config

warnings.filterwarnings("ignore")

test_texts = [
    # JVNVコーパスのテキスト
    # https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus
    # CC BY-SA 4.0
    "ああ？どうしてこんなに荒々しい態度をとるんだ？落ち着いて話を聞けばいいのに。",
    "いや、あんな醜い人間を見るのは本当に嫌だ。",
    "うわ、不景気の影響で失業してしまうかもしれない。どうしよう、心配で眠れない。",
    "今日の山登りは最高だった！山頂で見た景色は言葉に表せないほど美しかった！あはは、絶頂の喜びが胸に溢れるよ！",
    "あーあ、昨日の事故で大切な車が全損になっちゃった。もうどうしようもないよ。",
    "ああ、彼は本当に速い！ダッシュの速さは尋常じゃない！",
    # 以下app.pyの説明文章
    "音声合成は、機械学習を活用して、テキストから人の声を再現する技術です。この技術は、言語の構造を解析し、それに基づいて音声を生成します。",
    "この分野の最新の研究成果を使うと、より自然で表現豊かな音声の生成が可能である。深層学習の応用により、感情やアクセントを含む声質の微妙な変化も再現することが出来る。",
]

predictor = torch.hub.load(
    "tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True
)

parser = argparse.ArgumentParser()
parser.add_argument("--model_name", "-m", type=str, required=True)
parser.add_argument("--device", "-d", type=str, default="cuda")
parser.add_argument("--output", "-o", type=str, default="mos.csv")

args = parser.parse_args()

model_name: str = args.model_name
device: str = args.device

model_path = Path(config.assets_root) / model_name

# .safetensorsファイルを検索
safetensors_files = model_path.glob("*.safetensors")


def get_model(model_file: Path):
    return Model(
        model_path=str(model_file),
        config_path=str(model_file.parent / "config.json"),
        style_vec_path=str(model_file.parent / "style_vectors.npy"),
        device=device,
    )


results = []

safetensors_files = list(safetensors_files)

logger.info(f"There are {len(safetensors_files)} models.")

for model_file in tqdm(safetensors_files):
    model = get_model(model_file)
    scores = []
    for i, text in enumerate(test_texts):
        sr, audio = model.infer(text)
        audio = audio.astype("float32")
        score = predictor(torch.from_numpy(audio).unsqueeze(0), sr).item()
        scores.append(score)
        logger.info(f"score: {score}")
    # `test_e10_s1000.safetensors`` -> 1000を取り出す
    step = int(model_file.stem.split("_")[2][1:])
    results.append((model_file.name, step, scores))
    del model

logger.success("All models have been evaluated:")
# meanの降順にソートして表示
results = sorted(results, key=lambda x: x[2][-1], reverse=True)
for model_file, step, scores in results:
    logger.info(f"{model_file}: {scores[-1]}")

with open(args.output, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model_path"] + ["step"] + test_texts + ["mean"])
    for model_file, step, scores in results:
        writer.writerow([model_file] + [step] + scores)

# step countと各MOSの値を格納するリストを初期化
steps = []
mos_values = []

# resultsからデータを抽出
for _, step, scores in results:
    steps.append(step)
    mos_values.append(scores)  # scores は MOS1, MOS2, MOS3,... のリスト

# DataFrame形式に変換
df = pd.DataFrame(mos_values, index=steps)
# ステップ数でソート
df = df.sort_index()

# 各MOSと平均値についての折れ線グラフを描画
for col in df.columns:
    plt.plot(df.index, df[col], label=f"MOS{col + 1}")

# 平均値の計算と描画
df["mean"] = df.mean(axis=1)
plt.plot(df.index, df["mean"], label="Mean", color="black", linewidth=2)

# グラフのタイトルと軸ラベルを設定
plt.title("TTS Model Naturalness MOS")
plt.xlabel("Step Count")
plt.ylabel("MOS")

# 凡例を表示
plt.legend()

# グラフを表示
plt.show()