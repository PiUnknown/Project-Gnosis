Create a complete high-fidelity UI design for "Project Gnosis" — a 
developer tool for automated code archaeology. This is a portfolio-grade 
web application. Design for desktop (1440px width) as the primary 
breakpoint.

=================================================================
PROJECT CONTEXT
=================================================================

Project Gnosis takes a public GitHub repository URL and runs a 
7-agent Python pipeline that produces a structured onboarding 
document, dependency graph, and complexity report.

The 7 agents run sequentially:
  1. Ingestion — fetches file tree from GitHub API
  2. AST Parser — parses syntax trees with tree-sitter
  3. Dependency Graph — builds import graph with NetworkX
  4. Complexity Scorer — scores cyclomatic complexity and tech debt
  5. Code RAG — embeds code chunks into ChromaDB
  6. Explainability — generates prose explanations via LLM
  7. Doc Generator — synthesizes everything into onboarding.md

Key outputs:
  - onboarding.md (the primary deliverable, full Markdown doc)
  - complexity_report.json (risk-scored files)
  - dependency_graph.html (interactive pyvis graph)
  - explanations.json (per-file LLM prose)
  - graph_data.json (dependency structure)

The user journey is three screens:
  Screen 1: Landing — enter a GitHub URL and options, submit
  Screen 2: Job Progress — watch the 7 agents run in real time
  Screen 3: Results — read the generated document, explore outputs

=================================================================
DESIGN SYSTEM
=================================================================

--- PHILOSOPHY ---
Classical academic seriousness meets modern developer tool.
The visual reference is the Nous Research Hermes Agent site 
(nousr.com/hermes). NOT startup SaaS. NOT cyberpunk. NOT minimal 
Vercel-style. This is a philosophical instrument rendered as software.

--- COLOR PALETTE ---
Primary background:    #1400FF  (deep electric blue — the Nous blue)
Secondary background:  #0F00CC  (slightly darker blue for panels)
Content area (light):  #F0F0FF  (very pale blue-white for readable text)
Accent / primary text: #FFFFFF  (pure white)
Secondary text:        rgba(255,255,255,0.65)
Tertiary / muted:      rgba(255,255,255,0.40)
Input field fill:      #FFFFFF  (white background)
Input text:            #1400FF  (blue text on white input)
Dividers / borders:    rgba(255,255,255,0.25)
Error state:           #FF3B3B
Success state:         #FFFFFF  (white, not green)

DO NOT USE anywhere: 
  - Any gray (#666, #999, zinc-*, slate-*)
  - Black (#000 or #09090b)
  - Green, teal, or emerald
  - Any warm colors
  ONLY blue and white.

--- TYPOGRAPHY ---

Font 1: Playfair Display
  Usage: Hero headings, section headings, large display numbers
  Style: Weight 400 (regular), ALL CAPS, very tight letter-spacing
  Sizes: 
    H1 (hero): 80px, line-height 0.95, letter-spacing -0.02em
    H2 (section): 52px, line-height 1.0
    Display number (progress %): 120px, line-height 1.0
  Color: Always #FFFFFF

Font 2: IBM Plex Mono
  Usage: Labels, nav items, button text, tags, status indicators,
         file paths, agent names, metadata, all form labels,
         tab navigation, download buttons
  Style: Weight 400 and 500, UPPERCASE, letter-spacing 0.08em
  Sizes:
    Nav / button text: 12px
    Labels: 11px
    Metadata / footer: 10px
    Agent names in pipeline: 13px
  Color: #FFFFFF or rgba(255,255,255,0.65) for secondary

Font 3: Inter
  Usage: Body copy, descriptions, markdown content, table data
         (non-label), tooltip text, explanatory paragraphs
  Style: Weight 400, sentence case, normal letter-spacing
  Sizes:
    Body: 16px, line-height 1.6
    Small body / caption: 14px, line-height 1.5
  Color: rgba(255,255,255,0.75) on blue backgrounds
         #0A0A1A (near-black) on light (#F0F0FF) backgrounds

--- BORDER RADIUS ---
ZERO border-radius on ALL elements.
Buttons: 0px radius
Inputs: 0px radius
Cards: 0px radius
Badges: 0px radius
Progress bars: 0px radius
Tabs: 0px radius
This is the defining visual rule. Sharp corners everywhere.

--- SPACING SYSTEM ---
Base unit: 8px
Common spacings: 8, 16, 24, 32, 48, 64, 96, 128px
Left column content padding: 96px horizontal
Hero vertical rhythm: 64px between major sections
Form field height: 56px
Button height: 56px
Agent row height: 64px

--- BORDERS ---
All borders: 1px solid rgba(255,255,255,0.25)
Focused input: 1px solid #FFFFFF
No drop shadows anywhere.
No box-shadow anywhere.
No glassmorphism.

--- INTERACTIVE STATES ---
Primary button (white fill, blue text):
  Default:  bg #FFFFFF, text #1400FF
  Hover:    bg transparent, border 1px white, text #FFFFFF
  Active:   bg rgba(255,255,255,0.9)
  Disabled: bg rgba(255,255,255,0.20), text rgba(255,255,255,0.40)

Secondary button (outlined):
  Default:  bg transparent, border 1px rgba(255,255,255,0.5), text #FFFFFF
  Hover:    bg #FFFFFF, text #1400FF, border #FFFFFF
  Active:   bg rgba(255,255,255,0.85)

Input field:
  Default:  bg #FFFFFF, border 1px rgba(255,255,255,0.25), text #1400FF
  Focus:    bg #FFFFFF, border 1px #FFFFFF, text #1400FF
  Error:    bg #FFFFFF, border 1px #FF3B3B
  
  Note: placeholder text in input is #1400FF at 40% opacity

=================================================================
CLASSICAL FIGURE — ATHENA (appears on Landing + Progress pages)
=================================================================

Position: Right half of the viewport, bleeding off right and bottom edge
Size: Approximately 600px wide, full viewport height
Type: Line-art / classical engraving style illustration of Athena
      — goddess of wisdom wearing a helmet, holding a spear,
      with a shield, robes flowing
Style: Rendered in #3D28FF (slightly lighter than background blue)
       Opacity: 0.28
       This is monochromatic — same blue family, NOT white outlines
       Should read as background texture, not foreground element
Mix-blend-mode: screen or luminosity on the blue background

The figure should be:
  - Positioned with her torso/upper body visible in the right column
  - Head and helmet near the top-right of the viewport
  - Figure bleeds off the right edge (partially cropped)
  - No rectangular frame or container — she floats on the background

If the actual SVG engraving cannot be generated:
  Create a placeholder using a radial gradient:
    - Center: rgba(61,40,255,0.5) at 0%
    - Edge: transparent at 70%
  Positioned in the same location
  Add annotation text: "REPLACE WITH ATHENA SVG ENGRAVING"
  The gradient should still communicate the asymmetric composition.

=================================================================
SCREEN 1: LANDING PAGE (Frame: 1440 × 900px minimum)
=================================================================

LAYOUT: Two-column split
  Left column: 600px wide, content
  Right column: 840px, Athena figure + background only (no text)
  Both columns share the #1400FF background

--- TOP NAVIGATION BAR ---
Full width, sitting above the two-column split
Height: 72px
Background: #1400FF (same as page, no separate nav background)
Border-bottom: 1px solid rgba(255,255,255,0.15)
Padding: 0 96px

Left: "◯ GNOSIS"
  Font: IBM Plex Mono, 14px, weight 500, letter-spacing 0.12em
  Color: #FFFFFF
  The ◯ is a thin circle character (Unicode ○ or similar)

Right: "CODE ARCHAEOLOGY AGENT"
  Font: IBM Plex Mono, 11px, weight 400, letter-spacing 0.14em
  Color: rgba(255,255,255,0.50)

--- LEFT CONTENT COLUMN ---
Padding: 0px left (flush to column edge), 96px left margin from page edge
Vertical centering: content block centered in remaining height below nav

HEADLINE BLOCK (below nav, ~200px from top of content area):
  Line 1: "UNDERSTAND"
    Font: Playfair Display, 80px, weight 400, ALL CAPS, letter-spacing -0.01em
    Color: #FFFFFF
    Line-height: 0.95
  
  Line 2: "ANY CODEBASE."
    Same as Line 1
    The period is part of the design — do not omit it
  
  Both lines left-aligned, no indentation

SUBHEADLINE (24px below headline):
  "Enter a public GitHub URL. Gnosis maps every import, scores every 
   function, and writes the onboarding document your team never did."
  Font: Inter, 16px, weight 400
  Color: rgba(255,255,255,0.65)
  Max-width: 420px
  Line-height: 1.6

FORM BLOCK (48px below subheadline):

  [Label row]
  "REPOSITORY URL" 
  Font: IBM Plex Mono, 11px, weight 500, letter-spacing 0.14em
  Color: rgba(255,255,255,0.65)
  Margin-bottom: 8px

  [URL Input field]
  Width: 480px (full left column usable width)
  Height: 56px
  Background: #FFFFFF
  Border: 1px solid rgba(255,255,255,0.30)
  Border-radius: 0px
  Padding: 0 20px
  Placeholder text: "https://github.com/owner/repo"
  Placeholder color: rgba(20,0,255,0.35)
  Input text color: #1400FF
  Font: IBM Plex Mono, 14px, weight 400
  
  Focused state: border becomes 1px solid #FFFFFF
  Error state: border becomes 1px solid #FF3B3B

  [Inline error message — shown below input on validation failure]
  "INVALID GITHUB URL — MUST MATCH github.com/owner/repo"
  Font: IBM Plex Mono, 10px, letter-spacing 0.1em
  Color: #FF3B3B
  Margin-top: 6px

  [Options row] (24px below input)
  Flex row, gap 32px

    Option A — MAX EXPLANATIONS:
      Label: "MAX EXPLANATIONS"
        Font: IBM Plex Mono, 10px, letter-spacing 0.14em
        Color: rgba(255,255,255,0.65)
        Margin-bottom: 8px
      Number input:
        Width: 72px
        Height: 40px
        Background: #FFFFFF
        Border: 1px solid rgba(255,255,255,0.30)
        Border-radius: 0px
        Text: "20" centered
        Font: IBM Plex Mono, 14px, weight 500
        Color: #1400FF
        Text-align: center

    Option B — SKIP LLM:
      Label: "SKIP LLM"
        Font: IBM Plex Mono, 10px, letter-spacing 0.14em
        Color: rgba(255,255,255,0.65)
        Margin-bottom: 8px
      Toggle switch:
        Width: 44px, Height: 24px
        Track (OFF): border 1px solid rgba(255,255,255,0.40), fill transparent
        Track (ON): fill #FFFFFF
        Thumb (OFF): rgba(255,255,255,0.60) filled circle
        Thumb (ON): #1400FF filled circle
        Border-radius on track: 0px (sharp rectangle toggle, not pill)
      
      Tooltip icon (?) next to label:
        16px circle with "?" in IBM Plex Mono
        Border: 1px solid rgba(255,255,255,0.40)
        Tooltip content: "Skips LLM calls. Pipeline completes 
                          faster but without per-file explanations."
        Tooltip: #0F00CC background, white text, 1px white border, 0px radius

  [SUBMIT BUTTON] (24px below options row)
  Text: "ANALYZE REPOSITORY →"
  Width: 480px (full input width)
  Height: 56px
  Background: #FFFFFF
  Text color: #1400FF
  Font: IBM Plex Mono, 13px, weight 500, letter-spacing 0.14em, UPPERCASE
  Border: none
  Border-radius: 0px
  
  Hover state: bg transparent, border 1px #FFFFFF, text #FFFFFF
  
  Loading state:
    Text: "SUBMITTING ···"
    Animated dots (···) pulse
    bg: rgba(255,255,255,0.30)
    Text: rgba(255,255,255,0.60)
    Cursor: not-allowed

--- FOOTER METADATA ---
Position: Bottom of left column, 40px from page bottom
Text: "v0.1.0 · 7-AGENT PIPELINE · TREE-SITTER · CHROMADB"
Font: IBM Plex Mono, 10px, weight 400, letter-spacing 0.12em
Color: rgba(255,255,255,0.35)

--- RIGHT COLUMN ---
Contains ONLY the Athena figure (described in CLASSICAL FIGURE section)
No text, no UI elements
The figure floats here at the specified opacity

=================================================================
SCREEN 2: JOB PROGRESS PAGE (Frame: 1440 × 900px)
=================================================================

Same #1400FF background. Athena figure visible in the background 
(same position as Landing, opacity 0.20 — slightly more subtle here 
since there is more UI content competing with it).

Nav bar: identical to Landing page.

Main content: full width, max-width 1200px, centered, padding 0 120px

Layout: two-column
  Left column (500px): agent pipeline list
  Right column (remaining): progress display + current status

--- REPO CONTEXT BAR ---
Height: 48px, full width
Border-bottom: 1px solid rgba(255,255,255,0.15)
Padding: 0 (aligned to content columns)

"ANALYZING" in IBM Plex Mono 10px weight 500 letter-spacing 0.14em rgba(255,255,255,0.50)
Then the repo URL: "github.com/tiangolo/fastapi" in IBM Plex Mono 12px weight 400 #FFFFFF
Gap between: 16px

Status pill (right-aligned in this bar):
  QUEUED:   border 1px rgba(255,255,255,0.30), text rgba(255,255,255,0.50), "QUEUED"
  RUNNING:  border 1px #FFFFFF, text #FFFFFF, "RUNNING", animated pulse border
  COMPLETE: border 1px #FFFFFF, text #FFFFFF, "COMPLETE ✓"
  FAILED:   border 1px #FF3B3B, text #FF3B3B, "FAILED"
  
  Font: IBM Plex Mono 10px weight 500 letter-spacing 0.14em
  Padding: 4px 12px, border-radius: 0px

--- LEFT COLUMN: AGENT PIPELINE ---
Padding-top: 64px
Label at top: "PIPELINE STATUS" — IBM Plex Mono 10px weight 500 
  letter-spacing 0.16em rgba(255,255,255,0.50), margin-bottom 32px

Each agent row:
  Height: 72px
  Border-bottom: 1px solid rgba(255,255,255,0.10)
  Flex row: align-items center
  No background (transparent on blue)
  
  Left: Step number
    [01], [02], ... [07]
    Font: IBM Plex Mono, 11px, weight 400, letter-spacing 0.08em
    Color: rgba(255,255,255,0.30)
    Width: 32px
  
  Center: Agent name + description
    Agent name: IBM Plex Mono, 13px, weight 500, letter-spacing 0.10em, #FFFFFF
    Description: Inter, 12px, rgba(255,255,255,0.45), margin-top 3px
    Flex column
  
  Right: Status indicator
    QUEUED:   "—" in rgba(255,255,255,0.25), IBM Plex Mono 11px
    RUNNING:  "RUNNING ···" — text #FFFFFF IBM Plex Mono 11px, 
              animated: the three dots appear one by one, then reset
    COMPLETE: "COMPLETE ✓" — text #FFFFFF IBM Plex Mono 11px weight 500
    FAILED:   "FAILED" — text #FF3B3B IBM Plex Mono 11px

  State-specific full-row treatments:
    COMPLETE row: no background change, just text state change
    RUNNING row: subtle left border 2px #FFFFFF on the row's left edge
    QUEUED rows below current: everything rgba(255,255,255,0.30) opacity

Agent list (in order):
  01 | INGESTION          | Fetching repository file tree from GitHub API
  02 | AST PARSER         | Parsing syntax trees with tree-sitter
  03 | DEPENDENCY GRAPH   | Building directed import graph with NetworkX
  04 | COMPLEXITY SCORER  | Scoring cyclomatic complexity and tech debt
  05 | CODE RAG           | Embedding code chunks into ChromaDB
  06 | EXPLAINABILITY     | Generating explanations via LLM
  07 | DOC GENERATOR      | Synthesizing all outputs into onboarding.md

--- RIGHT COLUMN: PROGRESS DISPLAY ---
Padding-top: 64px
Flex column, justify-center (vertically centered in available height)

Large progress percentage:
  Text: "67%"
  Font: Playfair Display, 120px, weight 400, ALL CAPS (not applicable for numbers)
  Color: #FFFFFF
  Letter-spacing: -0.02em
  Line-height: 1.0

Current phase label (16px below the number):
  Text: "COMPLEXITY SCORER"
  Font: IBM Plex Mono, 12px, weight 500, letter-spacing 0.16em
  Color: rgba(255,255,255,0.65)

Progress bar (24px below phase label):
  Width: 300px
  Height: 1px (thin line — not thick)
  Background track: rgba(255,255,255,0.20)
  Fill: #FFFFFF
  Fill width: 67% of total (matches the number)
  No border-radius (sharp ends)
  The fill should have a sharp right edge, not a rounded cap

Sub-label below bar (12px below bar):
  Text: "4 OF 7 AGENTS COMPLETE"
  Font: IBM Plex Mono, 10px, weight 400, letter-spacing 0.14em
  Color: rgba(255,255,255,0.40)

--- COMPLETED STATE (show when all agents done) ---
Replaces or overlays the progress number area:
  Large text: "COMPLETE"
  Font: Playfair Display, 80px, weight 400, ALL CAPS
  Color: #FFFFFF
  
  Below: "ANALYSIS COMPLETE — VIEW RESULTS" button
  Same styling as CTA button on Landing page (white fill, blue text)
  Width: 280px, height: 56px
  Font: IBM Plex Mono 12px weight 500 letter-spacing 0.14em

--- FAILED STATE ---
Large text: "FAILED"
Font: Playfair Display, 80px, weight 400, ALL CAPS
Color: #FF3B3B

Error message below in IBM Plex Mono 12px rgba(255,255,255,0.65)
"← START OVER" secondary button below that

=================================================================
SCREEN 3: RESULTS PAGE (Frame: 1440 × 1024px)
=================================================================

Nav bar: identical to other pages.

Background: #1400FF (same blue) — but the main content tabs use 
the light (#F0F0FF) background for readability. The nav and tab bar 
remain blue.

--- RESULTS HEADER (below nav, blue background section) ---
Height: 120px
Padding: 32px 96px
Border-bottom: 1px solid rgba(255,255,255,0.15)

Repo name and branch (flex row):
  "TIANGOLO/FASTAPI" — IBM Plex Mono 18px weight 500 letter-spacing 0.10em #FFFFFF
  "ON MAIN" — IBM Plex Mono 12px weight 400 letter-spacing 0.12em rgba(255,255,255,0.50), margin-left 16px

Stats row (margin-top 12px, flex row, gap 32px):
  Each stat: 
    Number: IBM Plex Mono 16px weight 500 #FFFFFF
    Label: IBM Plex Mono 10px weight 400 letter-spacing 0.12em rgba(255,255,255,0.50) below number
  
  Stats to show:
    "87" / "FILES"
    "312" / "FUNCTIONS"  
    "24" / "CLASSES"
    "156" / "IMPORT EDGES"
    "15" / "EXPLAINED"

Risk distribution pills (margin-top 16px, flex row, gap 8px):
  Each pill: IBM Plex Mono 10px weight 500 letter-spacing 0.12em, 
             padding 3px 10px, border-radius 0px
  
  CRITICAL: bg #FFFFFF text #1400FF — "CRITICAL: 2"
  HIGH:     border 1px #FFFFFF text #FFFFFF bg transparent — "HIGH: 8"
  MEDIUM:   border 1px rgba(255,255,255,0.40) text rgba(255,255,255,0.65) — "MEDIUM: 18"
  LOW:      text rgba(255,255,255,0.40) no border — "LOW: 59"

Circular dep warning (only if circular deps exist):
  "⚠ 3 CIRCULAR DEPENDENCY CYCLES DETECTED"
  IBM Plex Mono 10px weight 500 letter-spacing 0.12em
  Color: #FFFFFF
  Background: rgba(255,255,255,0.10)
  Padding: 6px 12px, border-radius 0px, border: 1px solid rgba(255,255,255,0.30)
  Position: right side of header row or below stats

--- TAB NAVIGATION BAR ---
Height: 52px
Background: #0F00CC (slightly darker blue)
Border-bottom: 1px solid rgba(255,255,255,0.15)
Padding: 0 96px

Tabs (flex row, gap 0, touching):
  "ONBOARDING DOC" | "DEPENDENCY GRAPH" | "COMPLEXITY REPORT" | "RAW OUTPUT"
  
  Each tab:
    Padding: 0 32px
    Height: 52px (full bar height)
    Font: IBM Plex Mono 11px weight 500 letter-spacing 0.14em UPPERCASE
    Color (inactive): rgba(255,255,255,0.45)
    Color (active): #FFFFFF
    Border-bottom (active): 2px solid #FFFFFF
    Border-bottom (inactive): none
    Background: transparent
    Hover: text #FFFFFF
    Border-radius: 0px
  
  Separator between tabs: 1px solid rgba(255,255,255,0.15) vertical line, 
    but not between active and its neighbors (remove those adjacent ones)

--- TAB CONTENT AREA ---
Background: #F0F0FF (pale blue-white)
Padding: 48px 96px
Min-height: calc(100vh - nav - header - tabs - download-bar)

NOTE: All text inside tab content areas renders on the #F0F0FF 
      light background. Color rules change here:
  Headings (from markdown h1/h2/h3): #1400FF
  Body text: #0A0A1A (near-black)
  File paths / code: #1400FF in IBM Plex Mono
  Table borders: rgba(20,0,255,0.15)
  Table header bg: rgba(20,0,255,0.06)
  Muted labels: rgba(10,10,26,0.50)

=== TAB 1: ONBOARDING DOC ===

Small toolbar above document (margin-bottom 24px):
  Left: "ONBOARDING DOCUMENT" — IBM Plex Mono 10px weight 500 
    letter-spacing 0.14em rgba(10,10,26,0.50)
  Right: "↓ DOWNLOAD .MD" — secondary button, 
    but inverted for light bg: border 1px #1400FF, text #1400FF
    On hover: bg #1400FF, text #FFFFFF
    IBM Plex Mono 10px weight 500 letter-spacing 0.12em

Markdown document container:
  Max-width: 760px
  Margin: 0 auto (centered in content area)
  
  Markdown style overrides:
    H1: Playfair Display 48px weight 400 ALL CAPS #1400FF margin-bottom 24px
    H2: Playfair Display 32px weight 400 ALL CAPS #1400FF margin-top 48px margin-bottom 16px
    H3: IBM Plex Mono 13px weight 500 letter-spacing 0.12em UPPERCASE #1400FF margin-top 32px margin-bottom 12px
    Body text: Inter 16px #0A0A1A line-height 1.7
    Code inline: IBM Plex Mono 13px #1400FF bg rgba(20,0,255,0.08) padding 2px 6px
    Code block: IBM Plex Mono 13px #0A0A1A bg rgba(20,0,255,0.04) 
                border 1px rgba(20,0,255,0.12) padding 20px 24px
    Links: #1400FF underline, hover #0F00CC
    Blockquote: border-left 2px solid #1400FF, padding-left 20px, 
                text rgba(10,10,26,0.65) italic
    Table: width 100%, border-collapse collapse
    TH: IBM Plex Mono 10px weight 500 letter-spacing 0.12em UPPERCASE 
        bg rgba(20,0,255,0.06) border 1px rgba(20,0,255,0.12) 
        color rgba(10,10,26,0.70) padding 10px 16px
    TD: Inter 14px #0A0A1A border 1px rgba(20,0,255,0.10) padding 10px 16px
    
  Show a realistic sample onboarding document in this frame:
    Include: # FASTAPI — ARCHITECTURE OVERVIEW (as h1)
    ## Project Summary (h2)
    A paragraph of Lorem Ipsum styled as actual architecture description
    ## Repository Statistics (h2)
    A small 2-column table with mock data
    ## Core Components (h2)
    ### fastapi/routing.py (h3)
    A paragraph of explanation text
    Some inline code: `APIRouter`, `add_api_route()`
    Show enough content that the document feels substantial

=== TAB 2: DEPENDENCY GRAPH ===

Two-panel layout within the content area:

Top section: "MOST IMPORTED FILES"
  Label: IBM Plex Mono 10px weight 500 letter-spacing 0.16em rgba(10,10,26,0.45) margin-bottom 16px
  
  Table (full width):
    Border: 1px solid rgba(20,0,255,0.15)
    No border-radius
    
    Header row: bg rgba(20,0,255,0.06), height 40px
      Columns: FILE | IMPORTED BY | IMPORTS | RISK
      Font: IBM Plex Mono 10px weight 500 letter-spacing 0.12em UPPERCASE rgba(10,10,26,0.50)
      Padding: 0 20px
    
    Data rows (10 rows, height 48px each):
      Border-bottom: 1px solid rgba(20,0,255,0.08)
      Hover: bg rgba(20,0,255,0.04)
      
      FILE column:
        Font: IBM Plex Mono 13px weight 400 #1400FF
        Show only filename (e.g. "routing.py" not full path)
      
      IMPORTED BY (number):
        Font: IBM Plex Mono 14px weight 500 #1400FF
        Text-align: center
      
      IMPORTS (number):
        Font: IBM Plex Mono 14px weight 400 rgba(10,10,26,0.65)
        Text-align: center
      
      RISK column: risk badges (see badge styles below in Complexity section)
    
    Show sample data:
      routing.py      | 24 | 8  | HIGH
      dependencies.py | 19 | 3  | MEDIUM
      applications.py | 17 | 12 | CRITICAL
      params.py       | 14 | 5  | LOW
      utils.py        | 12 | 2  | LOW
      (5 more rows with decreasing numbers)

Bottom section (margin-top 48px): "SUGGESTED READING ORDER"
  Label: same style as above
  Note: "Files ordered so each appears after everything it depends on." 
    Inter 13px rgba(10,10,26,0.50) margin-bottom 16px

  Numbered list:
    Each row: flex row, height 40px, border-bottom 1px rgba(20,0,255,0.08)
    Number: IBM Plex Mono 11px rgba(10,10,26,0.35) weight 400, width 28px
    Path: IBM Plex Mono 13px weight 400 #1400FF
    
    Show 10 items with realistic Python file paths:
      01 | fastapi/types.py
      02 | fastapi/_compat.py
      03 | fastapi/exceptions.py
      ... etc

=== TAB 3: COMPLEXITY REPORT ===

Controls row (margin-bottom 24px):
  Flex row, items-center, gap 16px
  
  Sort dropdown:
    Height 40px, border 1px rgba(20,0,255,0.20), bg #FFFFFF
    Text: IBM Plex Mono 11px weight 500 letter-spacing 0.10em #1400FF UPPERCASE
    Selected: "SORT BY RISK ▾"
    Border-radius: 0px
    Arrow: #1400FF
  
  Filter input:
    Height 40px, border 1px rgba(20,0,255,0.20), bg #FFFFFF
    Placeholder: "FILTER BY FILENAME..."
    Placeholder color: rgba(20,0,255,0.35)
    Text: IBM Plex Mono 12px #1400FF
    Width: 240px
    Border-radius: 0px
  
  Count (right-aligned, ml-auto):
    "SHOWING 12 OF 87 FILES"
    IBM Plex Mono 10px weight 400 letter-spacing 0.10em rgba(10,10,26,0.40)

Risk badges (for use in this table and header):
  CRITICAL:
    Background: #1400FF
    Text: #FFFFFF
    Font: IBM Plex Mono 9px weight 500 letter-spacing 0.12em
    Padding: 3px 8px
    Border-radius: 0px
    Text: "CRITICAL"
  
  HIGH:
    Background: transparent
    Border: 1px solid #1400FF
    Text: #1400FF
    Same font/padding
    Text: "HIGH"
  
  MEDIUM:
    Background: rgba(20,0,255,0.08)
    Border: 1px solid rgba(20,0,255,0.20)
    Text: rgba(20,0,255,0.70)
    Same font/padding
    Text: "MEDIUM"
  
  LOW:
    Background: transparent
    Border: none
    Text: rgba(10,10,26,0.35)
    Same font/padding
    Text: "LOW"

Complexity table:
  Full width, border 1px rgba(20,0,255,0.15)
  
  Header: bg rgba(20,0,255,0.06), height 44px
    Columns (IBM Plex Mono 10px weight 500 letter-spacing 0.12em UPPERCASE rgba(10,10,26,0.45) padding 0 16px):
    FILE | RISK | AVG CC | MAX CC | WORST FUNCTION | COUPLING | FLAGS
  
  Rows (height 52px, border-bottom 1px rgba(20,0,255,0.08)):
    Hover: bg rgba(20,0,255,0.03)
    
    FILE: IBM Plex Mono 13px weight 400 #1400FF (filename only, no path)
    RISK: risk badge
    AVG CC: IBM Plex Mono 14px weight 500 #0A0A1A center
    MAX CC: IBM Plex Mono 14px weight 500 
            Normal: #0A0A1A
            If ≥21: #1400FF (highlighted as dangerous)
    WORST FUNCTION: IBM Plex Mono 12px weight 400 #1400FF (truncated)
    COUPLING: IBM Plex Mono 13px weight 400 rgba(10,10,26,0.65) center
    FLAGS: Small inline tags:
      "⚠ PARSE ERROR" — IBM Plex Mono 9px #FF3B3B
      "↻ CYCLE" — IBM Plex Mono 9px rgba(20,0,255,0.70)

  Show 8 sample rows with varied risk levels (2 CRITICAL, 3 HIGH, 2 MEDIUM, 1 LOW)
  Sample data should look realistic: 
    routing.py | CRITICAL | 12.4 | 27 | validate_request | 8 | ↻ CYCLE
    etc.

=== TAB 4: RAW OUTPUT ===

Four collapsible sections:

Each section:
  Header (height 52px, flex row items-center):
    Background: transparent (on #F0F0FF)
    Border: 1px solid rgba(20,0,255,0.15)
    Border-bottom (if collapsed): 1px solid rgba(20,0,255,0.15)
    Border-bottom (if expanded): none (removed to blend with content)
    Padding: 0 20px
    Margin-bottom (between sections): 12px
    
    Left: Section title — IBM Plex Mono 12px weight 500 letter-spacing 0.10em #0A0A1A UPPERCASE
          Subtitle (item count) — IBM Plex Mono 10px weight 400 rgba(10,10,26,0.40) ml-12px
    
    Right: "COPY" button
      Height 28px, border 1px rgba(20,0,255,0.30), bg transparent
      Text: IBM Plex Mono 9px weight 500 letter-spacing 0.12em #1400FF UPPERCASE
      Padding: 0 10px
      Hover: bg #1400FF, text #FFFFFF, border #1400FF
      
      Copied state: "COPIED ✓" text #1400FF
      
      Chevron icon (right of COPY): ▾ / ▴ indicating expanded/collapsed
        IBM Plex Mono rgba(10,10,26,0.40)
  
  Expanded content:
    Border: 1px solid rgba(20,0,255,0.15), border-top none
    Padding: 20px
    Max-height: 320px, overflow-y auto
    Background: rgba(20,0,255,0.03)
    
    JSON text:
      Font: IBM Plex Mono 12px weight 400
      Color: #0A0A1A
      White-space: pre
      Line-height: 1.6
      
      JSON syntax coloring:
        Keys: #1400FF
        String values: rgba(10,10,26,0.80)
        Numbers: #0F00CC
        Booleans/null: rgba(10,10,26,0.50)
  
  Four sections in order:
    1. "SUMMARY" — "12 FIELDS" — result.summary data
    2. "EXPLANATIONS" — "15 FILES EXPLAINED" — result.explanations data
    3. "COMPLEXITY REPORT" — "23 FLAGGED FILES" — result.complexity_report data
    4. "GRAPH SUMMARY" — "10 FILES TRACKED" — result.graph_summary data
  
  Default state: Section 1 expanded, sections 2-4 collapsed

--- STICKY DOWNLOAD BAR ---
Position: Fixed, bottom 0, full width
Height: 64px
Background: #1400FF
Border-top: 1px solid rgba(255,255,255,0.20)
Padding: 0 96px
Flex row, items-center, gap 16px

Left label:
  "DOWNLOAD OUTPUTS"
  IBM Plex Mono 10px weight 500 letter-spacing 0.16em rgba(255,255,255,0.45)

Three buttons (gap 12px between them, ml-24px after label):
  Each button:
    Height: 36px
    Border: 1px solid rgba(255,255,255,0.45)
    Background: transparent
    Text: #FFFFFF
    Font: IBM Plex Mono 10px weight 500 letter-spacing 0.12em UPPERCASE
    Padding: 0 16px
    Border-radius: 0px
    Hover: bg #FFFFFF, text #1400FF, border #FFFFFF
  
  Button texts:
    "↓ ONBOARDING.MD"
    "↓ COMPLEXITY_REPORT.JSON"
    "↓ DEPENDENCY_GRAPH.JSON"

=================================================================
COMPONENT LIBRARY (as reusable components in Figma)
=================================================================

Create a dedicated "Components" page with:

1. Color swatches for all palette colors with hex labels
2. Typography scale specimens for each font/size combination
3. Button states: Primary (all 4 states), Secondary (all 4 states)
4. Input field states: Default, Focus, Error
5. Toggle switch states: Off and On
6. Risk badges: CRITICAL, HIGH, MEDIUM, LOW (both blue-bg and white-bg versions)
7. Tab bar (active and inactive states)
8. Progress bar (various fill amounts: 0%, 33%, 67%, 100%)
9. Agent row states: QUEUED, RUNNING, COMPLETE
10. Status pills: QUEUED, RUNNING, COMPLETE, FAILED
11. Collapsible section: Collapsed and Expanded states
12. TopBar component

=================================================================
ADDITIONAL DESIGN NOTES
=================================================================

1. ICON STYLE: Use Unicode characters or simple geometric marks 
   rather than icon libraries. Examples: ◯ ✓ → ↓ ⚠ ↻ ···
   This matches the typographic aesthetic.

2. LOADING STATES: Show a spinner on the results page loading state
   The spinner: two concentric circles, outer ring with a white gap 
   (not filled), no border-radius on anything — angular segments 
   suggested by IBM Plex Mono text: "|" "/" "—" "\" cycling

3. ERROR STATES: Show on each page
   Error banner: border 1px solid #FF3B3B, bg rgba(255,59,59,0.08)
   on blue pages or rgba(255,59,59,0.06) on light pages
   Text: IBM Plex Mono 12px #FF3B3B weight 500 letter-spacing 0.10em

4. EMPTY STATES (no data for a section):
   Centered in the content area
   Large "—" in Playfair Display 48px rgba(20,0,255,0.20)
   Below: IBM Plex Mono 11px rgba(10,10,26,0.40) letter-spacing 0.12em
   Example: "NO COMPLEXITY DATA AVAILABLE"

5. SCROLLBAR: On the light (#F0F0FF) content area — 
   Custom scrollbar: track rgba(20,0,255,0.08), 
   thumb rgba(20,0,255,0.25), width 6px, no border-radius

6. ENSURE the Figma frames are: 
   Landing: 1440 × 900px
   Progress: 1440 × 900px  
   Results: 1440 × 1024px (taller to show download bar)
   Mobile frames (375px): optional, design desktop-first

7. PROTOTYPE CONNECTIONS (if supported by Figma Make):
   Landing CTA → Progress page
   Progress "View Results →" → Results page
   Gnosis nav logo → Landing page

8. EXPORT SETTINGS: Set all frames for 2x PNG export.
   Include in the Figma file: 
   - A "Flows" cover frame at 1440×600 showing all 3 screens side-by-side
     with the title "PROJECT GNOSIS — UI SYSTEM" in Playfair Display 48px #1400FF
     on #F0F0FF background

The design must feel inevitable — like this is the only correct way 
to visualize a code archaeology tool. Classical. Precise. Serious.