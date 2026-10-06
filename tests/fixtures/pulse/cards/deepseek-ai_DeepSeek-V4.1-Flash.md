---
license: mit
library_name: transformers
pipeline_tag: image-text-to-text
---

# DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression

<!-- markdownlint-disable first-line-h1 -->
<!-- markdownlint-disable html -->
<!-- markdownlint-disable no-duplicate-header -->

<div align="center">
  <img src="https://github.com/deepseek-ai/DeepSeek-V2/blob/main/figures/logo.svg?raw=true" width="60%" alt="DeepSeek-V4.1" />
</div>
<hr>
<div align="center" style="line-height: 1;">
  <a href="https://www.deepseek.com/" target="_blank" style="margin: 2px;">
    <img alt="Homepage" src="https://github.com/deepseek-ai/DeepSeek-V2/blob/main/figures/badge.svg?raw=true" style="display: inline-block; vertical-align: middle;"/>
  </a>
  <a href="https://chat.deepseek.com/" target="_blank" style="margin: 2px;">
    <img alt="Chat" src="https://img.shields.io/badge/🤖%20Chat-DeepSeek%20V4.1-536af5?color=536af5&logoColor=white" style="display: inline-block; vertical-align: middle;"/>
  </a>
</div>
<div align="center" style="line-height: 1;">
  <a href="https://huggingface.co/deepseek-ai" target="_blank" style="margin: 2px;">
    <img alt="Hugging Face" src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-DeepSeek%20AI-ffc107?color=ffc107&logoColor=white" style="display: inline-block; vertical-align: middle;"/>
  </a>
  <a href="https://twitter.com/deepseek_ai" target="_blank" style="margin: 2px;">
    <img alt="Twitter Follow" src="https://img.shields.io/badge/Twitter-deepseek_ai-white?logo=x&logoColor=white" style="display: inline-block; vertical-align: middle;"/>
  </a>
</div>
<div align="center" style="line-height: 1;">
  <a href="LICENSE" style="margin: 2px;">
    <img alt="License" src="https://img.shields.io/badge/License-MIT-f5de53?&color=f5de53" style="display: inline-block; vertical-align: middle;"/>
  </a>
</div>

<p align="center">
  <a href="https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/DeepSeek_V41_Tech_Report.pdf"><b>Technical Report</b> 👁️</a>
</p>

## Introduction

We introduce **DeepSeek-V4.1-Flash**, a multimodal Mixture-of-Experts (MoE) model with 552B backbone parameters and support for contexts of up to one million tokens. The model natively processes images and text, and generates text autoregressively.

**Architecture.** DeepSeek-V4.1-Flash adopts a **Causal Encoder-Decoder (CED)** architecture: a 40-layer Transformer organized as a 20-layer causal encoder followed by a 20-layer decoder. With CED, the decoder's global KV cache is projected from the final encoder hidden states rather than derived from each decoder layer's own hidden states. This allows the model to activate only **8B parameters per token during prefill** and **16B during decode**, substantially improving cost efficiency for input-heavy agentic workloads. **SWA Bounded Replay** reconstructs missing SWA KV states by replaying only the most recent *n*_win tokens, avoiding the need to persist SWA KV to SSD and reducing the persistent KV cache footprint to roughly **1/8** of that of DeepSeek-V4-Flash.

**Compressed Sparse Attention 2 (CSA2).** DeepSeek-V4.1-Flash uses CSA2, which assigns each attention layer one of three static modes — **Full**, **Reindex**, or **Reuse** — to share main KV and indexer K across layers and reuse Top-K sparse-attention indices. In the decoder, a **Hierarchical Sparse Indexer** further restricts later indexing layers to a candidate pool constructed by the first Full Mode layer, bounding deeper indexer cost independently of context length. Combined with **FP4 main KV caching** (E2M1 format, one E4M3 scale per 16 channels), these designs reduce the global KV cache footprint to **890 bytes per token** — roughly **1/4** of DeepSeek-V4-Flash.

**Additional architectural components** include Single-Pass mHC (revised residual-stream mixing with an efficient Mega-mHC kernel), Engram conditional memory (196B parameters, sparsely accessed via token-based lookup), and DSpark speculative decoding (semi-autoregressive draft generation with confidence-scheduled verification). The model uses 1 shared expert and 384 routed experts per MoE layer, activating 6 routed experts per token.

**Multimodal architecture.** A vision encoder (DeepSeek-ViT, trained from scratch with 2D-RoPE and 3×3 pixel-unshuffle downsampling) and a two-layer MLP projector convert images into visual embeddings, processed jointly with text embeddings from the start of language-model pre-training.

**Pre-training.** DeepSeek-V4.1-Flash is trained from scratch on a multimodal corpus comprising **45T tokens**, with sparse attention trained at a sequence length of 64K and context extended to 1M tokens at 34T tokens.

**Post-training.** The post-training recipe follows the standard SFT → RL → on-policy distillation (OPD) paradigm without algorithmic modifications. All substantive changes lie instead in the data pipeline: large-scale automated synthesis of agent tasks and environments with progressive scaling of data, tasks, and rollouts. The model supports a **continuously controllable reasoning effort** setting (integer 1–100) that trades inference cost for accuracy.

<div align="center">
  <img src="assets/dsv41_agentic_performance.png" width="48%" alt="DeepSeek-V4.1-Flash agentic benchmark performance" style="display: inline-block; margin: 0 1%;" />
  <img src="assets/dsv41_kv_cache.png" width="48%" alt="Global KV cache size per token across DeepSeek generations" style="display: inline-block; margin: 0 1%;" />
</div>

*Figure 1. (a) Performance of DeepSeek-V4.1-Flash and counterparts on agentic benchmarks. (b) Global KV cache size per token (bytes) across generations of DeepSeek models. DeepSeek-V4.1-Flash achieves approximately 4-fold and 437-fold reductions relative to DeepSeek-V4-Flash and DeepSeek-V1, respectively.*

## Evaluation Results

### Base Model

