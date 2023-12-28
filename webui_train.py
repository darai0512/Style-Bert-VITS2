import json
import os
import shutil
import subprocess
import sys

import gradio as gr
import yaml

python = sys.executable


def subprocess_wrapper(cmd):
    return subprocess.run(
        map(lambda x: str(x), cmd),
        stdout=sys.stdout,
        stderr=subprocess.PIPE,
        text=True,
    )


def get_path(model_name):
    assert model_name != "", "モデル名は空にできません"
    dataset_path = os.path.join("Data", model_name)
    lbl_path = os.path.join(dataset_path, "esd.list")
    train_path = os.path.join(dataset_path, "train.list")
    val_path = os.path.join(dataset_path, "val.list")
    config_path = os.path.join(dataset_path, "config.json")
    return dataset_path, lbl_path, train_path, val_path, config_path


def initialize(model_name, batch_size, epochs, bf16_run):
    dataset_path, _, train_path, val_path, config_path = get_path(model_name)
    if os.path.isfile(config_path):
        config = json.load(open(config_path, "r", encoding="utf-8"))
    else:
        # Use default config
        config = json.load(open("configs/config.json", "r", encoding="utf-8"))
    config["model_name"] = model_name
    config["data"]["training_files"] = train_path
    config["data"]["validation_files"] = val_path
    config["train"]["batch_size"] = batch_size
    config["train"]["epochs"] = epochs
    config["train"]["bf16_run"] = bf16_run

    model_path = os.path.join(dataset_path, "models")
    try:
        shutil.copytree(src="pretrained", dst=model_path)
    except FileExistsError:
        return f"Error: モデルフォルダ {model_path} が既に存在します。問題なければ削除してください。"
    except FileNotFoundError:
        return "Error: pretrainedフォルダが見つかりません。"

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    if not os.path.exists("config.yml"):
        shutil.copy(src="default_config.yml", dst="config.yml")
    # yml_data = safe_load(open("config.yml", "r", encoding="utf-8"))
    with open("config.yml", "r", encoding="utf-8") as f:
        yml_data = yaml.safe_load(f)
    yml_data["model_name"] = model_name
    yml_data["dataset_path"] = dataset_path
    with open("config.yml", "w", encoding="utf-8") as f:
        yaml.dump(yml_data, f, allow_unicode=True)
    return "Step 1: 初期設定が完了しました"


def resample(model_name, num_processes: int):
    dataset_path, _, _, _, _ = get_path(model_name)
    in_dir = os.path.join(dataset_path, "raw")
    out_dir = os.path.join(dataset_path, "wavs")
    result = subprocess_wrapper(
        [
            python,
            "resample.py",
            "--in_dir",
            in_dir,
            "--out_dir",
            out_dir,
            "--sr",
            "44100",
            "--num_processes",
            num_processes
        ]
    )
    if result.stderr:
        return f"{result.stderr}"
    return "Step 2: 音声ファイルの前処理が完了しました"


def preprocess_text(model_name):
    dataset_path, lbl_path, train_path, val_path, config_path = get_path(model_name)
    lines = open(lbl_path, "r", encoding="utf-8").readlines()
    with open(lbl_path, "w", encoding="utf-8") as f:
        for line in lines:
            path, spk, language, text = line.strip().split("|")
            path = os.path.join(dataset_path, "wavs", os.path.basename(path)).replace(
                "\\", "/"
            )
            f.writelines(f"{path}|{spk}|{language}|{text}\n")
    result = subprocess_wrapper(
        [
            python,
            "preprocess_text.py",
            "--config-path",
            config_path,
            "--transcription-path",
            lbl_path,
            "--train-path",
            train_path,
            "--val-path",
            val_path,
        ]
    )

    if result.stderr:
        return f"{result.stderr}"
    return "Step 3: 書き起こしファイルの前処理が完了しました"


def bert_gen(model_name, num_processes: int):
    _, _, _, _, config_path = get_path(model_name)
    result = subprocess_wrapper(
        [python, "bert_gen.py", "--config", config_path, "--num_processes", num_processes]
    )
    if result.stderr:
        return f"{result.stderr}"
    return "Step 4: BERT特徴ファイルの生成が完了しました"


def style_gen(model_name, num_processes: int):
    _, _, _, _, config_path = get_path(model_name)
    result = subprocess_wrapper(
        [
            python,
            "style_gen.py",
            "--config",
            config_path,
            "--num_processes",
            num_processes,
        ]
    )
    if result.stderr:
        return f"{result.stderr}"
    return "Step 5: スタイル特徴ファイルの生成が完了しました"


def train(model_name):
    dataset_path, _, _, _, config_path = get_path(model_name)
    result = subprocess_wrapper(
        [python, "train_ms.py", "--config", config_path, "--model", dataset_path]
    )
    if result.stderr:
        return f"{result.stderr}"
    return "Final Step: 学習が完了しました!"


initial_md = """
# Style-Bert-VITS2 学習用WebUI

## 使い方

- データを準備して、各ステップを順に実行してください。進捗状況等はターミナルに表示されます。

- 途中から学習を再開する場合は、モデル名を入力してFinal Stepだけ実行すればよいです。

注意: 音声合成で使うには、スタイルベクトルファイル`style_vectors.npy`を作る必要があります。これは、`Style.bat`を実行してそこで作成してください。
動作は軽いはずなので、学習中でも実行でき、何度でも繰り返して試せます。
"""

prepare_md = """
まず音声データ（wavファイルで1ファイルが2-15秒程度の、長すぎず短すぎない発話のものをいくつか）と、書き起こしテキストを用意してください。

それを次のように配置します。
```
├── Data
│   ├── {モデルの名前}
│   │   ├── esd.list
│   │   ├── raw
│   │   │   ├── ****.wav
│   │   │   ├── ****.wav
│   │   │   ├── ...
```

wavファイル名やモデルの名前は空白を含まない半角で、wavファイルの拡張子は小文字`.wav`である必要があります。
`raw` フォルダにはすべてのwavファイルを入れ、`esd.list` ファイルには、以下のフォーマットで各wavファイルの情報を記述してください。
```
****.wav|{話者名}|{言語ID、ZHかJPかEN}|{書き起こしテキスト}
```

例：
```
wav_number1.wav|hanako|JP|こんにちは、聞こえて、いますか？
wav_next.wav|taro|JP|はい、聞こえています……。
english_teacher.wav|Mary|EN|How are you? I'm fine, thank you, and you?
...
```
日本語話者の単一話者データセットでも構いません。
"""

css = """
/* マークダウン要素のスタイル */
div.panel {
    justify-content: space-between;
}

"""

if __name__ == "__main__":
    with gr.Blocks(theme="NoCrypt/miku", css=css) as app:
        gr.Markdown(initial_md)
        with gr.Accordion(label="データの前準備", open=False):
            gr.Markdown(prepare_md)
        model_name = gr.Textbox(
            label="モデル名",
        )
        num_processes = gr.Slider(
            label="スレッドサイズ",
            info="学習の各前処理の実行時のCPUスレッド数",
            value=2,
            minimum=1,
            maximum=16,
            step=1,
        )
        info = gr.Textbox(label="状況")
        with gr.Row(variant="panel"):
            with gr.Column(variant="panel", min_width=160):
                gr.Markdown(value="Step 1: 設定ファイルの生成")
                batch_size = gr.Slider(
                    label="バッチサイズ",
                    info="VRAM 12GBで4くらい",
                    value=4,
                    minimum=1,
                    maximum=64,
                    step=1,
                )
                epochs = gr.Slider(
                    label="エポック数",
                    info="100もあれば十分そう",
                    value=100,
                    minimum=1,
                    maximum=1000,
                    step=1,
                )
                bf16_run = gr.Checkbox(
                    label="bfloat16を使う",
                    info="新しめのグラボだと学習が早くなるかも、古いグラボだと動かないかも",
                    value=True,
                )
                generate_config_btn = gr.Button(value="実行", variant="primary")
            with gr.Column(variant="panel", min_width=160):
                gr.Markdown(value="Step 2: 音声ファイルの前処理")
                resample_btn = gr.Button(value="実行", variant="primary")
            with gr.Column(variant="panel", min_width=160):
                gr.Markdown(value="Step 3: 書き起こしファイルの前処理")
                preprocess_text_btn = gr.Button(value="実行", variant="primary")
            with gr.Column(variant="panel", min_width=160):
                gr.Markdown(value="Step 4: BERT特徴ファイルの生成")
                bert_gen_btn = gr.Button(value="実行", variant="primary")
            with gr.Column(variant="panel", min_width=160):
                gr.Markdown(value="Step 5: スタイル特徴ファイルの生成")
                style_gen_btn = gr.Button(value="実行", variant="primary")
        with gr.Row(variant="panel"):
            with gr.Column():
                gr.Markdown(value="Final Step: 学習")
                train_btn = gr.Button(value="学習", variant="primary")

        generate_config_btn.click(
            initialize,
            inputs=[model_name, batch_size, epochs, bf16_run],
            outputs=[info],
        )
        resample_btn.click(resample, inputs=[model_name, num_processes], outputs=[info])
        preprocess_text_btn.click(preprocess_text, inputs=[model_name], outputs=[info])
        bert_gen_btn.click(
            bert_gen, inputs=[model_name, num_processes], outputs=[info]
        )
        style_gen_btn.click(
            style_gen, inputs=[model_name, num_processes], outputs=[info]
        )
        train_btn.click(train, inputs=[model_name], outputs=[info])

    app.launch(share=False, inbrowser=True)
