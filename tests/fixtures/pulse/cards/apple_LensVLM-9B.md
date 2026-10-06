---
license: apple-amlr
license_link: https://huggingface.co/apple/LensVLM-9B/blob/main/LICENSE
library_name: transformers
pipeline_tag: image-text-to-text
base_model:
- Qwen/Qwen3.5-9B
tags:
- vision-language-model
- long-context
- visual-text-compression
---

# LensVLM-9B

LensVLM is a 9B Vision Language Model (VLM) that scans compressed images of text,
then selectively expands only the relevant pages to their uncompressed form via
learned tools.

- Paper: [LensVLM: Selective Context Expansion for Compressed Visual Representation of Text](https://arxiv.org/abs/2605.07019)
- Code: https://github.com/apple-aiml-research/ml-lensvlm

## License

All ML model files in this repository, including Apple's modifications to the Qwen
model, are provided under the terms of the
[Apple Machine Learning Research Model License](https://huggingface.co/apple/LensVLM-9B/blob/main/LICENSE).

The source code that accompanies this model is distributed separately and is provided
under the terms of the Apple Sample Code License.

## Usage

Install the LensVLM code and run inference:

```bash
git clone https://github.com/apple-aiml-research/ml-lensvlm
cd ml-lensvlm
pip install -r requirements.txt
python scripts/run_demo.py --model apple/LensVLM-9B
```

For a custom document:

```bash
python demo.py \
    --model apple/LensVLM-9B \
    --text_file document.txt \
    --question "What is the main finding?" \
    --compression 10x
```

Compression options: `5x`, `10x`, `15x`. See the
[repository README](https://github.com/apple-aiml-research/ml-lensvlm) for data preparation
and evaluation.

## Citation

```bibtex
@article{xie2026lensvlm,
  title={LensVLM: Selective Context Expansion for Compressed Visual Representation of Text},
  author={Xie, Roy and Friedman, Dan and Yu, Donghan and Pan, Bowen and Fifty, Christopher and Kim, Jang-Hyun and Du, Xianzhi and Gan, Zhe and Rathod, Vivek and Dhingra, Bhuwan},
  journal={arXiv preprint arXiv:2605.07019},
  year={2026}
}
```
