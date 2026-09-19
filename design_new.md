# GNOSIS DESIGN LANGUAGE SYSTEM (TECH-BRUTALIST BLUEPRINT)
`DOCUMENT_ID: DESIGN-SPEC-V2`  
`STATUS: ACTIVE_SPECIFICATION`  
`THEME: ARCHAEOLOGICAL FIELD NOTEBOOK // ENGINEERING BLUEPRINT`

---

## 1. PHILOSOPHY & CONCEPT
Gnosis reads dead code and brings back its structural architecture.  
The visual aesthetic represents an **archaeological field notebook crossed with an engineering blueprint**: technical, dense, precise, slightly hand-annotated. An engineer's workbench, not a marketing website. Dark mode only.

---

## 2. CORE STYLE (3 MANDATORY INGREDIENTS)
1. **Blueprint / Schematic Base**:
   - Faint engineering grid background (1px lines, 4–6% opacity, 8px/24px modular repeat).
   - Crosshair registration marks (`+`), corner ticks, coordinate-style captions (`SEC 04 // LAT 45.22`, `GRID [04, 12]`).
   - Tiny ALL-CAPS monospaced annotation labels.
2. **Tech-Brutalist UI**:
   - Monospaced typography for ALL data, numbers, headers, and metadata labels.
   - Dense modular panels with 1px solid borders (`#26262A`).
   - No rounded corners (maximum 0–2px radius).
   - No gradients on chrome, no drop shadows. Everything looks printed by a precision machine.
3. **HUD / Telemetry Readouts**:
   - Scores, counts, distributions as instrument panels.
   - Horizontal bar meters (`[■■■■■■□□□□] 60%`), dot matrices, sparklines.
   - Micro-stats formatted as calibration instruments (`CALIBRATION 100%`, `DEPTH 4`, `CHROMA_CHUNKS 240`).
   - Numbers feel *measured*, not merely displayed.

---

## 3. DESIGN TOKENS

### Color Palette
| Token | Hex | Role |
|---|---|---|
| `--bg-base` | `#0A0A0B` | Canvas / Root background |
| `--bg-panel` | `#121214` | Modular panel surface |
| `--border-subtle` | `#26262A` | 1px panel and separator borders |
| `--border-active` | `#3F3F46` | Active / focused panel borders |
| `--text-primary` | `#E8E8E6` | Primary titles, active values, high contrast |
| `--text-secondary` | `#8A8A85` | Descriptions, labels, secondary metrics |
| `--text-micro` | `#55554F` | 10-11px microtext, coordinate tags, glyphs |
| `--accent-amber` | `#E8A33D` | **ONLY** accent color. Used sparingly for active states, key risk metrics, and doodle annotations |

### Typography
- **Monospace (Data, Labels, Telemetry, Code)**: `JetBrains Mono`, `IBM Plex Mono`, `ui-monospace`, `monospace`.
- **Grotesque Sans (Headings)**: `Space Grotesk`, `Inter`, `sans-serif`.
- **Microtext Spec**: Monospace, `10px - 11px`, `ALL CAPS`, `letter-spacing: 0.08em`, `font-weight: 500`.

### Spatial & Layout Rules
- **8px Grid**: All margins, paddings, and panel gaps adhere to multiples of 8px.
- **Edge-to-Edge Tiling**: Panels tile with 1px gaps or borders; no nested cards-in-cards.
- **Strict Anti-Decorations**:
  - NO glassmorphism or blur effects.
  - NO neumorphism or soft shadows.
  - NO background gradients on UI chrome.
  - NO rounded friendly buttons or cards.
  - NO stock illustrations, 3D blobs, or purple-blue SaaS gradients.
  - NO emojis in the UI.

---

## 4. COMPONENT ARCHITECTURE & SPECS

### 4.1 Panel Containers (`BlueprintPanel`)
- Surface: `#121214`, Border: `1px solid #26262A`, Radius: `0px` (or max `2px`).
- Header: Monospace ALL-CAPS microtext + thin 1px horizontal rule + status glyph (e.g. `[●]`, `[01_EXCAVATION]`, `[SYS_OK]`).
- Optional corner crosshairs or registration ticks.

### 4.2 Buttons (`TechButton`)
- Flat rectangle, 1px solid border (`#26262A` or `#E8A33D`).
- Typography: Uppercase monospace.
- Interaction: Inverts on hover (background turns `#E8E8E6` or `#E8A33D`, text turns `#0A0A0B`).
- Active / Loading: ASCII animation indicator (`[■ PROCESSING...]`).

### 4.3 Telemetry & Meter Readouts
- **Segmented Bar Meter (`TelemetryMeter`)**: Discrete step blocks (`■■■■■□□□□□`) or percentage line with tick marks.
- **Dot Matrix (`DotMatrixReadout`)**: Dense dot grid showing density, risk distribution, or embedding cluster states.
- **Sparklines (`SparklineReadout`)**: Monospaced ASCII or 1px stroke SVG telemetry curves.
- **Stat Instruments (`StatInstrument`)**: Measured reading with uppercase label (`REPOS INDEXED 12`, `PARSE DEPTH 4`, `CALIBRATION 100%`).

### 4.4 Loaders & Empty States
- **Loading State**: ASCII progress bar fill (`[=======>    ] 65%`) or dot-matrix cycling. No circular spinners.
- **Empty State**: Minimal wireframe blueprint schematic + single-line monospace caption.

---

## 5. DOODLE ACCENTS & FIELD ANNOTATIONS
- **Purpose**: Sparse hand-drawn marker squiggles over the technical blueprint base (max 1–2 per screen).
- **Function**: Highlights the single most critical item on screen (e.g., highest architectural risk hotspot, circular dependency cycle, primary action).
- **Asset Slots**:
  - Loaded via `<img>` tags pointing to `/assets/doodles/[filename].svg` with configurable sizing and positioning.
  - Graceful fallback: If image file is missing, falls back to inline SVG geometric line marks (amber `#E8A33D` hand-drawn loop, arrow, or underline) or technical bracket annotation.
  - No AI-generated or runtime generated raster images.

---

## 6. MICROCOPY GUIDELINES
All labels and descriptions must read like scientific instrument telemetry:
- `EXCAVATE REPOSITORY` (not "Analyze Code")
- `AST PARSER DEPTH: 4` (not "We look deep into files")
- `INDEXED NODES: 1,420` (not "Awesome, 1,420 files found!")
- `CYCLOMATIC DEFICIT DETECTED` (not "Warning: complex code")
- `RESTORING ARCHITECTURAL ONBOARDING DOC` (not "Generating your docs")
