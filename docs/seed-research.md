# Seed Research — On-Prem AI Adoption Radar (2026)

Research date: 2026-06-12. All URLs verified live via web fetch/search. Star counts are approximate snapshots.
Proposed seeds avoid the already-seeded set (Cline, OpenHands, Aider, OpenClaw, Hermes, Goose, MCP, NemoClaw, LangGraph, AutoGen, vLLM, SGLang, NVIDIA Dynamo, KubeAI, KAITO, NVIDIA GPU Operator, Blackwell/GB200, Huawei Ascend).

| Project | Category | URL | Maturity (stars/license) | Why on-prem matters | Verified |
|---------|----------|-----|--------------------------|---------------------|----------|
| Continue | coding_agents | https://github.com/continuedev/continue | ~33.7k / Apache-2.0 (repo now read-only; pivoted to Continue CLI, source-controlled AI checks in CI) | Open-source coding agent runnable against self-hosted/local models; CLI usable in air-gapped CI | yes |
| OpenCode | coding_agents | https://github.com/sst/opencode | ~174k / MIT | Open-source terminal coding agent, model-agnostic; pairs with local/self-hosted inference | yes |
| Tabby | coding_agents | https://github.com/TabbyML/tabby | ~33.6k / open-source (Apache-style, LICENSE in repo) | Purpose-built self-hosted Copilot alternative, no DBMS dependency, consumer-GPU friendly — core on-prem coding fit | yes |
| MCP Registry | mcp_tooling | https://github.com/modelcontextprotocol/registry | ~6.9k / OSS (LICENSE in repo) | Self-hostable "app store" for MCP servers; lets enterprises run a private curated tool catalog | yes |
| GitHub MCP Server | mcp_tooling | https://github.com/github/github-mcp-server | ~30.6k / MIT | Reference production MCP server; self-hostable, shows MCP tool-access surface for governance/risk scoring | yes |
| E2B | sandbox_governance | https://github.com/e2b-dev/e2b | ~12.6k / Apache-2.0 | Open-source isolated sandboxes for agent-generated code; self-hostable for enterprise-grade agents | yes |
| gVisor | sandbox_governance | https://github.com/google/gvisor | ~18.5k / Apache-2.0 | Userspace application kernel (runsc) for strong container isolation — foundational on-prem agent sandboxing | yes |
| Microsandbox | sandbox_governance | https://github.com/microsandbox/microsandbox | ~6.5k / Apache-2.0 (beta) | Hardware-isolated microVMs (<100ms boot) for running untrusted agent code on-prem; ships MCP server | yes |
| CrewAI | agent_frameworks | https://github.com/crewAIInc/crewAI | ~53.3k / MIT | Lean multi-agent orchestration framework, LangChain-independent; runnable fully on local/self-hosted models | yes |
| Pydantic-AI | agent_frameworks | https://github.com/pydantic/pydantic-ai | ~17.7k / MIT | Production-grade, validation-first agent framework; provider-agnostic incl. Ollama/self-hosted | yes |
| Agno | agent_frameworks | https://github.com/agno-agi/agno | ~40.7k / Apache-2.0 | Build/run/manage agent platforms with self-hostable control plane, tracing, scheduling | yes |
| Ollama | model_serving | https://github.com/ollama/ollama | ~174k / MIT | The de-facto local model runner; OpenAI-compatible API, single-binary on-prem deployment | yes |
| llama.cpp | model_serving | https://github.com/ggml-org/llama.cpp | ~116k / MIT | Dependency-free C/C++ inference (CPU/CUDA/HIP/Metal); llama-server gives OpenAI-compatible on-prem endpoint | yes |
| LocalAI | model_serving | https://github.com/mudler/LocalAI | ~46.8k / MIT | Privacy-first OpenAI/Anthropic-compatible engine; runs LLM/vision/voice on any hardware, no GPU required | yes |
| LMDeploy | model_serving | https://github.com/InternLM/lmdeploy | ~7.9k / Apache-2.0 | High-throughput LLM serving (TurboMind), strong throughput vs vLLM; self-hosted GPU inference | yes |
| TensorRT-LLM | model_serving | https://github.com/NVIDIA/TensorRT-LLM | ~13.9k / Apache-2.0 | NVIDIA-optimized LLM inference for on-prem GPU clusters; integrates with Triton | yes |
| KServe | ai_infrastructure | https://github.com/kserve/kserve | ~5.6k / Apache-2.0 (CNCF incubating) | Standardized K8s inference platform (gen + predictive); the on-prem serving control plane | yes |
| Ray | ai_infrastructure | https://github.com/ray-project/ray | ~42.9k / Apache-2.0 | Distributed AI compute engine; scales training/serving from laptop to on-prem cluster | yes |
| Volcano | ai_infrastructure | https://github.com/volcano-sh/volcano | ~5.7k / Apache-2.0 (CNCF incubating) | K8s-native batch/gang scheduler for AI/ML — critical for on-prem GPU job scheduling | yes |
| NVIDIA NIM | ai_infrastructure | https://www.nvidia.com/en-us/ai-data-science/products/nim-microservices/ | Product page / proprietary | Prebuilt optimized inference microservices deployable in the data center; enterprise on-prem path | yes |
| AMD Instinct MI300X | physical_ai_infrastructure | https://www.amd.com/en/products/accelerators/instinct/mi300/mi300x.html | Product page / hardware | 192GB HBM3 accelerator; leading non-NVIDIA on-prem option, drives vendor diversity | yes |
| Intel Gaudi 3 | physical_ai_infrastructure | https://www.intel.com/content/www/us/en/products/details/processors/ai-accelerators/gaudi.html | Product page / hardware | Ethernet-based scaling, open networking; cost-effective on-prem training/inference alternative | yes |
| Tenstorrent tt-metal | physical_ai_infrastructure | https://github.com/tenstorrent/tt-metal | ~1.5k / Apache-2.0 | Open low-level stack (TT-Metalium/TT-NN) for Tenstorrent accelerators; open-hardware on-prem bet | yes |

## Notes / dropped candidates
- **Roo Code** (https://github.com/RooCodeInc/Roo-Code): repo ARCHIVED 2026-05-15, maintainers recommend Cline (already seeded). Dropped — declining signal.
- **Codex CLI** (https://github.com/openai/codex, ~90.7k, Apache-2.0): real and large, but tightly coupled to OpenAI cloud models — weak on-prem fit vs. OpenCode/Continue. Dropped to keep coding_agents on-prem-biased.
- **TGI / text-generation-inference** (https://github.com/huggingface/text-generation-inference): ARCHIVED 2026-03-21, maintainers redirect to vLLM/SGLang (already seeded). Dropped.
- **Triton Inference Server** (https://github.com/triton-inference-server/server, ~10.8k, BSD-3): verified and strong, but model_serving quota already well-covered; held as a bench alternative to TensorRT-LLM.
- **Strands Agents** (https://github.com/strands-agents/sdk-python, ~6.1k, Apache-2.0): verified, AWS-led; held as agent_frameworks bench depth behind CrewAI/Pydantic-AI/Agno.
- **BentoML** (https://github.com/bentoml/BentoML, ~8.7k, Apache-2.0), **Kubeflow** (https://github.com/kubeflow/kubeflow, ~15.7k, Apache-2.0), **Megatron-LM** (https://github.com/NVIDIA/Megatron-LM, ~16.7k, Apache-2.0), **llm-d** (https://github.com/llm-d/llm-d, ~3.3k, Apache-2.0): all verified live; held as bench depth to respect category quotas.
- All 23 proposed seeds were verified live. None could NOT be verified.
