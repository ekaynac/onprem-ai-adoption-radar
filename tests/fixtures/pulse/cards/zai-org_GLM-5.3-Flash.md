---
language:
- en
- zh
library_name: transformers
license: mit
pipeline_tag: image-text-to-text
---

# GLM-5.3-Flash

<div align="center">
<img src=https://raw.githubusercontent.com/zai-org/GLM-5/refs/heads/main/resources/logo.svg width="15%"/>
</div>
<p align="center">
    👋 Join our <a href="https://raw.githubusercontent.com/zai-org/GLM-5/refs/heads/main/resources/wechat.png" target="_blank">WeChat</a> or <a href="https://discord.gg/QR7SARHRxK" target="_blank">Discord</a> community.
    <br>
    📖 Check out the GLM-5.3-Flash <a href="https://z.ai/blog/glm-5.3-flash" target="_blank">blog</a> and GLM-5 <a href="https://arxiv.org/abs/2602.15763" target="_blank">Technical report</a>.
    <br>
    📍 Use GLM-5.3-Flash API services on <a href="https://docs.z.ai/guides/llm/glm-5.3-flash">Z.ai API Platform. </a>
</p>

## Introduction

We introduce GLM-5.3-Flash, the first natively multimodal model in the GLM-5 series. With 320B total parameters and just 18B active parameters, it outperforms GLM-5.2 across benchmarks and real-world workloads at one-tenth the price, while approaching Claude Opus 4.8 on coding and agentic benchmarks.

GLM-5.3-Flash starts from a newly trained base model, with its architecture and training recipe redesigned around capability and efficiency. For the first time in the GLM series, we introduce a hybrid architecture combining sparse and linear attention, sharply reducing long-context serving costs while preserving precise long-context capabilities. The model also adopts Manifold-Constrained Hyper-Connections (mHC) to further improve scaling efficiency. Together with our latest 30T-token multimodal pre-training corpus, these changes enable GLM-5.3-Flash to deliver more intelligence with less compute.

![bench_53](https://raw.githubusercontent.com/zai-org/GLM-5/refs/heads/main/resources/bench_53.png)


## Serve GLM-5.3-Flash Locally

GLM-5.3-Flash supports deployment with the following frameworks. Feel free to try them out:

- [SGLang](https://github.com/sgl-project/sglang) — see [cookbook](https://cookbook.sglang.io/autoregressive/GLM/GLM-5.3-Flash)
- [vLLM](https://github.com/vllm-project/vllm) — see [recipes](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash)
- [TokenSpeed](https://github.com/lightseekorg/tokenspeed) — see [here](https://lightseek.org/tokenspeed/recipes/models#glm-5-3-flash)
- [Transformers](https://github.com/huggingface/transformers) — see [transformers docs](https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/glm5_next.md)
- [KTransformers](https://github.com/kvcache-ai/ktransformers) — see [tutorial](https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/kt-kernel/GLM-5.3-Flash-Tutorial.md)
- [Unsloth](https://github.com/unslothai/unsloth) — see [guide](https://unsloth.ai/docs/models/glm-5.3)

### Note

- GLM-5.3-Flash supports controlling the thinking budget through the `reasoning_effort` parameter, which accepts three levels: `low`, `high`, and `max`. It defaults to `max` if not passed (or if set to any other value). To use `low` or `high`, pass them explicitly. For benchmark and leaderboard reproduction, keep the default `max`.
- In the chat template for GLM-5.3-Flash, `clear_thinking` defaults to `false` if not passed. For chat scenarios, explicitly pass `clear_thinking=true`.

## Footnotes

* **HLE w/ tools (full set)**: We use sampling parameters of `temperature=1.0` and `top_p=0.95` for evaluation, with a maximum generation length of `163,840` tokens. The evaluation is conducted with a maximum context length of `300,000` tokens, using a context management strategy. We use GPT-5.6-luna (medium) as the judge model.
* **NL2Repo**: We evaluated NL2Repo with temperature=1.0, top_p=1.0, and max_new_tokens=64k under 1M context. To prevent hacking, we use rule-based and a LLM-based judgement to prevent malicious behaviors (e.g., unauthorized pip or curl operations).
* **DeepSWE**: We run DeepSWE using the mini-swe-agent harness with `temperature=0.95`, `top_p=1.0`, `timeout=6h` and 400K context.
* **Terminal-Bench 2.1**: We evaluate in Claude Code 2.1.207 with temperature=1.0, top_p=1, max_new_tokens=65536 with 6h timeout.
* **Agent’s Last Exam**: 
* **Toolathlon Verified**: We obtain all results via the official evaluation service and report pass@1 averaged over 3 independent runs.
* **AutomationBench**: We evaluate on AutomationBench **v1.0.6**, incorporating the fix for the `null`-type handling issue introduced in [PR #13](https://github.com/zapier/AutomationBench/pull/13).
* **GDPval-AA v2**: Models are evaluated by Artificial Analysis.
* **BabyVision**: We use temperature=1.0, top_p=0.95, and a maximum context length of 164K tokens. We resize the input images such that their shorter side is at least 1.5K pixels, consistent with other baselines.

## Citation

If you find GLM-5.3-Flash useful in your research, please cite our technical report:

```bibtex
@misc{glm5team2026glm5vibecodingagentic,
      title={GLM-5: from Vibe Coding to Agentic Engineering},
