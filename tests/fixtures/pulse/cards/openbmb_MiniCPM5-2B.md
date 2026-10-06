---
license: apache-2.0
language:
  - en
  - zh
library_name: transformers
pipeline_tag: text-generation
tags:
  - minicpm
  - minicpm5
  - llama
  - text-generation
  - long-context
  - tool-calling
  - on-device
  - edge-ai
datasets:
  - openbmb/Ultra-FineWeb
  - openbmb/UltraX-Preview
  - openbmb/Ultra-FineWeb-L3
  - openbmb/UltraData-Math
  - openbmb/UltraData-Code
  - openbmb/UltraData-SFT-2605
  - openbmb/UltraData-SFT-Agent-2609
  - openbmb/UltraData-RL-2609
---

<div align="center">
<img src="https://raw.githubusercontent.com/OpenBMB/MiniCPM/main/assets/minicpm_logo.png" width="500em" />
</div>

<p align="center">
<a href="https://arxiv.org/pdf/2506.07900" target="_blank">MiniCPM Tech Report</a> |
<a href="https://modelbest.feishu.cn/wiki/UtWxwcERfiRIpIkBOjuc3h9tn1D" target="_blank">MiniCPM Wiki(Chinese)</a> |
<a href="https://github.com/OpenBMB/MiniCPM" target="_blank">GitHub Repo</a> |
<a href="https://ultradata.openbmb.cn/" target="_blank">UltraData</a> |
<a href="https://huggingface.co/spaces/openbmb/MiniCPM5-2B-Demo" target="_blank">Online Demo</a>
</p>

<p align="center">
English |
<a href="https://huggingface.co/openbmb/MiniCPM5-2B/blob/main/README-cn.md" target="_blank">中文</a>
</p>

## Highlights

We are releasing **MiniCPM5-2B**, the second model in the **MiniCPM5** series, following [MiniCPM5-1B](https://huggingface.co/openbmb/MiniCPM5-1B). It is a dense 2B Transformer that scales up the same training recipe, built for on-device, local deployment, and resource-constrained scenarios, reaching 2B-class open-source SOTA.

🏆 **2B-class open-source SOTA**: compared with strong open-source models of similar size, MiniCPM5-2B achieves SOTA performance within this comparison set. It remains competitive with 4B-class models overall, while showing its advantages over models of comparable size in coding, mathematics, long-context understanding, tool use, and agentic tasks.

<div id="capability-comparison-radar" class="radar-visual" role="img" aria-label="Capability radar chart comparing MiniCPM5-2B with 4B-class models. Each axis is normalized independently to 100 percent.">
  <style>
    #capability-comparison-radar {
      --foreground: #171717;
      display: block; width: 100%; max-width: 620px; margin: 0 auto; background: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }
    #capability-comparison-radar svg { display: block; width: 100%; height: auto; background: #fff; }
    #capability-comparison-radar .title { fill: var(--foreground); font-size: 16px; font-weight: 600; letter-spacing: 0; }
    #capability-comparison-radar .axis-label { fill: #333; font-size: 12px; font-weight: 600; }
    #capability-comparison-radar .ring { fill: none; stroke: rgba(128,128,128,.18); stroke-width: .8; }
    #capability-comparison-radar .spoke { stroke: rgba(128,128,128,.25); stroke-width: .8; }
    #capability-comparison-radar .ring-label { fill: #8a8a8a; font-size: 9px; }
    #capability-comparison-radar .series { stroke-linejoin: round; }
    #capability-comparison-radar .series.primary { stroke-width: 2.4; }
    #capability-comparison-radar .legend-label { fill: #171717; font-size: 12px; font-weight: 600; }
    #capability-comparison-radar .legend-average { fill: #666; font-size: 11px; }
    #capability-comparison-radar .legend-swatch { rx: 3; }
    @media (max-width: 900px) { #capability-comparison-radar { overflow-x: auto; } #capability-comparison-radar svg { min-width: 620px; } }
  </style>
  <svg viewBox="0 0 680 560" aria-hidden="true">
    <g transform="translate(-20 0)">
      <text x="40" y="28" class="title" text-anchor="start">Capability Radar by Dimension</text>
      <polygon points="340.0,235.0 362.5,243.2 374.5,263.9 370.3,287.5 352.0,302.9 328.0,302.9 309.7,287.5 305.5,263.9 317.5,243.2" class="ring" stroke="rgba(128,128,128,.18)" stroke-width=".8"/>
      <text x="344.0" y="238.0" class="ring-label">20%</text>
      <polygon points="340.0,200.0 385.0,216.4 408.9,257.8 400.6,305.0 363.9,335.8 316.1,335.8 279.4,305.0 271.1,257.8 295.0,216.4" class="ring" stroke="rgba(128,128,128,.18)" stroke-width=".8"/>
      <text x="344.0" y="203.0" class="ring-label">40%</text>
      <polygon points="340.0,165.0 407.5,189.6 443.4,251.8 430.9,322.5 375.9,368.7 304.1,368.7 249.1,322.5 236.6,251.8 272.5,189.6" class="ring" stroke="rgba(128,128,128,.18)" stroke-width=".8"/>
      <text x="344.0" y="168.0" class="ring-label">60%</text>
      <polygon points="340.0,130.0 430.0,162.8 477.9,245.7 461.2,340.0 387.9,401.6 292.1,401.6 218.8,340.0 202.1,245.7 250.0,162.8" class="ring" stroke="rgba(128,128,128,.18)" stroke-width=".8"/>
      <text x="344.0" y="133.0" class="ring-label">80%</text>
      <polygon points="340.0,95.0 452.5,135.9 512.3,239.6 491.6,357.5 399.9,434.4 280.1,434.4 188.4,357.5 167.7,239.6 227.5,135.9" class="ring" stroke="rgba(29,111,208,.28)" stroke-width="1"/>
      <text x="344.0" y="98.0" class="ring-label">100%</text>
      <line x1="340" y1="270" x2="340.0" y2="95.0" class="spoke"/>
      <text x="340.0" y="63.5" class="axis-label" text-anchor="middle">Code Reasoning</text>
      <line x1="340" y1="270" x2="452.5" y2="135.9" class="spoke"/>
      <text x="472.7" y="111.8" class="axis-label" text-anchor="start">Math Reasoning</text>
      <line x1="340" y1="270" x2="512.3" y2="239.6" class="spoke"/>
      <text x="543.4" y="234.1" class="axis-label" text-anchor="start">Instruction Following</text>
      <line x1="340" y1="270" x2="491.6" y2="357.5" class="spoke"/>
      <text x="518.8" y="373.2" class="axis-label" text-anchor="start">General Knowledge</text>
      <line x1="340" y1="270" x2="399.9" y2="434.4" class="spoke"/>
      <text x="410.6" y="464.0" class="axis-label" text-anchor="start">Long Context</text>
      <line x1="340" y1="270" x2="280.1" y2="434.4" class="spoke"/>
      <text x="269.4" y="464.0" class="axis-label" text-anchor="end">Tool Use</text>
