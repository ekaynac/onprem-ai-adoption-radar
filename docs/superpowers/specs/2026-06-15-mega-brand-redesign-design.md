# Mega Bilişim Corporate Rebrand — Design

**Date:** 2026-06-15
**Status:** Approved & implemented

## Goal
Rebrand the On-Prem AI Adoption Radar dashboard and static site to the
**Mega Bilişim Teknolojileri** corporate design standard, at "faithful
corporate" fidelity, with an **English** UI.

## Source of truth
The brand standard lives in the Open Design project `mega-design-standard`
(`design-standard.md`). The visual was generated with the **Open Design app**
(Claude/Sonnet agent) into `radar-mega.html`, then ported into the radar's
shared, no-build template system.

## Brand tokens (from the standard)
- **Process Blue** `#009FDA` (primary: hero band, links, adopt accents, focus).
- **Cool Gray 3** `#BCBEC0`; surfaces `#E8E8E9` / `#F0F0F0`; Black `#1A1A1A`; White.
- **Typography:** Centrale Sans (700/400) with `system-ui` fallback (licensed
  font; activated by dropping web fonts at `static/brand/centrale-sans/`).
- **Buka dot-pattern:** subtle radial-gradient texture (white on the blue hero,
  Cool Gray on the footer).

## Decisions
- **Fidelity:** faithful corporate (not expressive/mascot-heavy).
- **Language:** English UI (data, MCP, repo are English); Turkish copy from the
  generated mockup not used.
- **Assets:** typographic `mega®` lockup + `local()` font now; real logo/font
  files can be added later under `static/brand/` (graceful fallback in place).

## Implementation
All styling lives in the shared `_base_styles.html` (used by the live dashboard
and the static export, so they cannot drift). The page structure — hero, stat
bar, legend, sticky filter, ring pills, backer badges, project pages, footer —
already matched the mockup, so the change is a palette + lockup + dot-pattern
rebrand plus a Mega attribution footer. Light + dark via `prefers-color-scheme`.
Brand presence is locked by a regression test
(`test_static_index_carries_mega_brand`).
