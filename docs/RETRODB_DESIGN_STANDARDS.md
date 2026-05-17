# RetroDB Design Standards Reference

> **Purpose**: This document defines all visual and UI standards for the RetroDB project. When provided to Claude in future conversations, it ensures consistent implementation of the cyberpunk/retro-futuristic design system.

---

## 1. Design Philosophy

**Theme**: Cyberpunk/Retro-Futuristic Dark Theme
**Aesthetic**: Neon glows, dark backgrounds, sci-fi typography, subtle animations
**Framework**: Flask/Jinja2 with vanilla CSS and JavaScript

### Core Principles
- Dark backgrounds with glowing neon accents
- Semi-transparent elements with subtle borders
- Glow effects on interactive elements
- Smooth transitions (0.15s - 0.4s)
- Scanline overlay for retro CRT feel
- Animated mist/fog background effect

---

## 2. Color System

### CSS Variables (defined in `:root`)

#### Primary Colors (Cyan - Main accent)
```css
--primary-cyan: #4cc9f0
--primary-cyan-dark: #3a9fc2
--primary-cyan-light: #7dd8f5
--primary-cyan-glow: rgba(76, 201, 240, 0.5)
--neon-cyan: #4cc9f0
```

#### Secondary Colors (Magenta - Secondary accent)
```css
--secondary-magenta: #f72585
--secondary-magenta-dark: #c41d6a
--secondary-magenta-light: #f95fa3
--secondary-magenta-glow: rgba(247, 37, 133, 0.5)
```

#### Accent Colors (Purple family)
```css
--accent-purple: #7209b7
--accent-blue: #3a0ca3
--accent-violet: #560bad
--neon-purple: #a855f7
```

#### Background Colors (Dark scale)
```css
--bg-darkest: #0a0e17     /* Page background */
--bg-dark: #0f1419
--bg-medium: #151b24
--bg-light: #1a222d
--bg-lighter: #212b38
```

#### Card Colors
```css
--card-bg: #141a23
--card-bg-hover: #1a222d
--card-border: #2a3542
--card-border-hover: #3a4552
```

#### Text Colors
```css
--text-primary: #e8eaed      /* Main text */
--text-secondary: #9aa0a6    /* Supporting text */
--text-muted: #6e7378        /* Disabled/subtle text */
--text-accent: var(--primary-cyan)
```

#### Status Colors
```css
--status-success: #00e676    /* Also --neon-green: #22c55e */
--status-warning: #ffab00    /* Also --neon-orange: #f59e0b */
--status-error: #ff5252      /* Also --neon-red: #ef4444 */
--status-info: var(--primary-cyan)
--neon-gray: #64748b
```

---

## 3. Typography

### Font Families
```css
--font-primary: 'Rajdhani', 'Orbitron', 'Share Tech Mono', sans-serif  /* Body text */
--font-heading: 'Orbitron', 'Rajdhani', sans-serif                      /* Headings */
--font-mono: 'Share Tech Mono', 'JetBrains Mono', monospace            /* Code/mono */
```

### Font Loading (in HTML head)
```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;600;700;800;900&family=Rajdhani:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
```

### Heading Hierarchy
| Element | Font | Size | Weight | Transform | Letter Spacing |
|---------|------|------|--------|-----------|----------------|
| h1 | Orbitron | 2rem | 700 | UPPERCASE | 1px |
| h2 | Orbitron | 1.5rem | 600 | - | 0.5px |
| h3 | Orbitron | 1.25rem | 600 | - | - |
| h4 | Rajdhani | 1.1rem | 600 | - | - |
| h5 | Rajdhani | 1rem | 600 | - | - |
| h6 | Rajdhani | 0.9rem | 500 | UPPERCASE | 0.5px |

### Page Title
- Font: `var(--font-heading)`
- Size: `2.5rem`
- Color: `var(--primary-cyan)`
- Transform: `uppercase`
- Letter spacing: `4px`
- Glow animation: `text-shadow` pulse effect

---

## 4. Spacing System

### CSS Variables
```css
--spacing-xs: 4px
--spacing-sm: 8px
--spacing-md: 16px
--spacing-lg: 24px
--spacing-xl: 32px
--spacing-2xl: 48px
```

### Border Radius
```css
--radius-sm: 4px
--radius-md: 8px
--radius-lg: 12px
--radius-xl: 16px
--radius-full: 9999px   /* For pills/circles */
```

---

## 5. Shadows & Effects

### Shadow Scale
```css
--shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.3)
--shadow-md: 0 4px 8px rgba(0, 0, 0, 0.4)
--shadow-lg: 0 8px 16px rgba(0, 0, 0, 0.5)
--shadow-xl: 0 12px 24px rgba(0, 0, 0, 0.6)
```

### Glow Effects
```css
--shadow-glow-cyan: 0 0 20px rgba(76, 201, 240, 0.3)
--shadow-glow-magenta: 0 0 20px rgba(247, 37, 133, 0.3)
```

### Transitions
```css
--transition-fast: 0.15s ease
--transition-normal: 0.25s ease
--transition-slow: 0.4s ease
```

---

## 6. UI Components

### 6.1 Buttons (Neon Style)

**Base Button Structure**:
```html
<button class="btn btn-{variant}">
    <span class="btn-icon">🎮</span>
    Button Text
</button>
```

**Variants**:
| Class | Border/Text Color | Glow Color |
|-------|-------------------|------------|
| `btn-primary` | #4cc9f0 (cyan) | rgba(76, 201, 240, 0.5) |
| `btn-secondary` | #64748b (gray) | rgba(100, 116, 139, 0.3) |
| `btn-success` | #22c55e (green) | rgba(34, 197, 94, 0.5) |
| `btn-warning` | #f59e0b (orange) | rgba(245, 158, 11, 0.5) |
| `btn-danger` | #ef4444 (red) | rgba(239, 68, 68, 0.5) |

**Button Style Properties**:
```css
.btn {
    padding: var(--spacing-md) var(--spacing-lg);
    font-family: var(--font-primary);
    font-size: 0.9rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    border: 2px solid;
    border-radius: var(--radius-md);
    background: rgba({color}, 0.15);
    box-shadow: 0 0 15px rgba({color}, 0.5),
                0 0 30px rgba({color}, 0.3),
                inset 0 0 20px rgba({color}, 0.1);
    text-shadow: 0 0 10px rgba({color}, 0.8);
}

.btn:hover {
    background: rgba({color}, 0.25);
    transform: translateY(-2px);
}
```

**Size Variants**:
- `btn-sm`: padding `var(--spacing-sm) var(--spacing-md)`, font `0.8rem`
- `btn-lg`: padding `var(--spacing-lg) var(--spacing-xl)`, font `1rem`

---

### 6.2 Toggle Switches (Replaces Checkboxes)

**IMPORTANT**: All boolean on/off controls use toggle switches, NOT checkboxes.

**HTML Structure**:
```html
<div class="toggle-item">
    <label class="toggle-switch">
        <input type="checkbox" name="setting_name">
        <span class="toggle-slider"></span>
    </label>
    <span class="toggle-label">Setting Label</span>
</div>
```

**Visual States**:
- **OFF**: Red background (`var(--neon-red)` #ef4444), white knob left
- **ON**: Green background (`var(--neon-green)` #22c55e), white knob right

**Dimensions**:
- Switch: 52px × 28px
- Knob: 22px diameter
- Border-radius: 28px (pill shape)

---

### 6.3 Text Inputs

**HTML Structure**:
```html
<div class="form-group">
    <label class="form-label">Label Text</label>
    <input type="text" class="form-input" placeholder="Placeholder...">
</div>
```

**Styling**:
```css
.form-input {
    width: 100%;
    padding: 0.75rem 1rem;
    background: var(--bg-dark);
    border: 1px solid var(--card-border);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-family: var(--font-primary);
    font-size: 0.95rem;
}

.form-input:focus {
    border-color: var(--neon-cyan);
    box-shadow: 0 0 0 2px rgba(76, 201, 240, 0.15),
                0 0 15px rgba(76, 201, 240, 0.2);
}
```

#### Inputs with Leading Icons (Search Boxes, etc.)

When placing an icon inside an input (e.g. a search magnifying glass), **never hardcode `padding-left`**. Instead, define CSS variables on the wrapper so the icon position, visual width, and input padding are derived from the same source:

```css
.search-box {
    --search-icon-offset: var(--spacing-md);   /* icon's left position              */
    --search-icon-size: 1.15rem;               /* icon's font-size                  */
    --search-icon-width: 2rem;                 /* visual width (emoji > font-size)  */
    --search-icon-gap: var(--spacing-sm);      /* gap between icon & text           */
    position: relative;
}

.search-icon {
    position: absolute;
    left: var(--search-icon-offset);
    font-size: var(--search-icon-size);
}

.search-input {
    /* padding is always: icon-offset + icon-width + gap */
    padding-left: calc(var(--search-icon-offset) + var(--search-icon-width) + var(--search-icon-gap));
}
```

**Rules:**
- The parent wrapper owns the four `--search-icon-*` variables
- `--search-icon-size` controls the icon's `font-size`
- `--search-icon-width` controls the **visual width allocation** used in padding — this must be larger than `--search-icon-size` because emoji glyphs render wider than their font-size
- The input derives `padding-left` from `offset + width + gap` via `calc()`
- Changing any variable automatically keeps icon and text aligned
- This pattern applies to **all** icon-inside-input components (`.search-box`, `.search-box-integrated`, `.psn-search-wrapper`, etc.)

---

### 6.4 Select / Dropdowns

**HTML Structure**:
```html
<select class="form-select">
    <option value="">Select option...</option>
    <option value="a">Option A</option>
    <option value="b">Option B</option>
</select>
```

**IMPORTANT**: Options should be sorted alphabetically in HTML/JS.

**Custom Arrow**: Cyan SVG arrow via `background-image`:
```css
background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%234cc9f0' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
```

---

### 6.5 Badges

**HTML Structure**:
```html
<span class="badge">Default Badge</span>
<span class="badge badge-success">Success</span>
<span class="badge badge-warning">Warning</span>
<span class="badge badge-danger">Danger</span>
<span class="badge badge-purple">Purple</span>
<span class="badge badge-secondary">Secondary</span>
```

**Styling**:
```css
.badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.75rem;
    background: rgba({color}, 0.15);
    border: 1px solid {color};
    border-radius: var(--radius-full);
    font-size: 0.8rem;
    font-weight: 500;
    color: {color};
}
```

---

### 6.6 Cards / Sections

**HTML Structure**:
```html
<div class="card">
    <div class="card-header">
        <h3 class="card-title">
            <span>⚙️</span> Card Title
        </h3>
    </div>
    <div class="card-body">
        Content here...
    </div>
</div>
```

**Styling**:
```css
.card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--radius-lg);
    padding: var(--spacing-lg);
}

.card:hover {
    border-color: var(--card-border-hover);
    box-shadow: var(--shadow-lg);
}
```

---

### 6.7 Progress Bars

**HTML Structure**:
```html
<div class="progress-container">
    <div class="progress-bar" style="width: 75%;">75%</div>
</div>
```

**Styling**:
```css
.progress-container {
    background: #1a1a3e;
    border: 2px solid var(--neon-cyan);
    border-radius: var(--radius-md);
    height: 36px;
    box-shadow: 0 0 15px rgba(76, 201, 240, 0.3);
}

.progress-bar {
    background: linear-gradient(90deg, var(--neon-cyan), #7209b3);
    color: white;
    font-weight: 700;
}
```

---

### 6.8 Tables

**HTML Structure**:
```html
<table class="data-table">
    <thead>
        <tr><th>Column 1</th><th>Column 2</th></tr>
    </thead>
    <tbody>
        <tr><td>Data 1</td><td>Data 2</td></tr>
    </tbody>
</table>
```

---

### 6.9 Alerts

**HTML Structure**:
```html
<div class="alert alert-success">Success message here</div>
<div class="alert alert-warning">Warning message here</div>
<div class="alert alert-error">Error message here</div>
<div class="alert alert-info">Info message here</div>
```

---

### 6.10 Breadcrumbs

**HTML Structure**:
```html
<div class="breadcrumb">
    <a href="/systems">Systems</a>
    <span class="breadcrumb-separator">›</span>
    <a href="/systems/nes">NES</a>
    <span class="breadcrumb-separator">›</span>
    <span class="breadcrumb-current">Super Mario Bros.</span>
</div>
```

**Important Guidelines**:
- **Do NOT include Dashboard** in breadcrumbs - navigation starts from the section root
- Examples: "Systems › NES › Game", "RetroAchievements › SNES", "PSN Trophies › Game"

---

### 6.11 Tabs

Tabs stretch to fill the available width.

**Tab Variants**:
| Class | Used On |
|-------|---------|
| `.tool-tabs` / `.tool-tab` | ROM Tools pages |
| `.system-tabs` / `.system-tab` | Achievements, Systems |
| `.report-tabs` / `.report-tab` | Reports page |
| `.settings-tabs` / `.settings-tab` | Settings page |

**Key CSS**:
```css
.tab {
    flex: 1 1 auto;  /* IMPORTANT: Tabs stretch to fill width */
    display: flex;
    align-items: center;
    justify-content: center;
}

.tab.active {
    background: rgba(76, 201, 240, 0.15);
    border-color: var(--primary-cyan);
    color: var(--primary-cyan);
    box-shadow: 0 0 15px rgba(76, 201, 240, 0.3);
}
```

---

## 7. Layout Structure

### Page Layout
```
┌──────────────────────────────────────────────────────────────┐
│ Sidebar (260px)        │  Main Content                       │
│                        │  ┌────────────────────────────────┐ │
│ Logo                   │  │ Content Wrapper                │ │
│ Nav Sections           │  │ (65% width, max 1400px)        │ │
│ Version Footer         │  └────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Sidebar Variables
```css
--sidebar-width: 260px
--sidebar-collapsed-width: 70px
```

### Sidebar Active States

Sidebar nav items highlight for both parent and child pages using `request.endpoint`:

```jinja2
{# Systems - active for systems, system_games, and game_detail from systems #}
{% if request.endpoint in ['systems.systems', 'systems.system_games', 'games.game_detail']
   and request.args.get('from') not in ['library', 'achievements'] %}active{% endif %}

{# Achievements - active for main, system, and game views #}
{% if request.endpoint in ['achievements.achievements', 'achievements.achievements_system', 'achievements.achievement_game'] %}active{% endif %}

{# PSN Trophies - active for list and detail #}
{% if request.endpoint in ['trophies.psn_trophies', 'trophies.psn_trophy_detail'] %}active{% endif %}
```

**Key**: Use `?from=library` or `?from=achievements` query params to track navigation context.

---

## 8. Theme System

### Available Themes
RetroDB supports 7 themes, each with CSS variable overrides and an animated canvas effect:

| Theme | `data-theme` | Primary | Secondary | Canvas Effect |
|-------|-------------|---------|-----------|---------------|
| Cyberpunk (default) | `cyberpunk` | `#4cc9f0` (cyan) | `#f72585` (magenta) | Volumetric smoke (simplex noise) |
| Matrix | `matrix` | `#00ff41` (green) | `#003300` | Digital rain (kanji) |
| Amber | `amber` | `#ffb000` (amber) | `#ff6600` | CRT terminal glow |
| Ocean | `ocean` | `#06b6d4` (teal) | `#0284c7` (blue) | Moon reflection with waves |
| Cathedral | `christian` | `#d4a843` (gold) | `#7b4db0` (purple) | Golden dust motes with light rays |
| Blade Runner | `bladerunner` | `#1a9fff` (electric blue) | `#ff2d7c` (neon pink) | Rain streaks with neon glow pools |
| Elite 1984 | `elite` | `#00ff00` (vector green) | `#00cc00` | 1984 vector starfield (stars streaming past) |

### Theme Implementation
- **CSS**: `[data-theme="name"]` selectors in `static/css/core/themes.css` override CSS variables
- **JS**: `ThemeManager` in `static/js/theme.js` manages switching, canvas effects, and persistence
- **FOUC Prevention**: Inline script in `base.html` applies theme before first paint
- **Persistence**: Stored in `localStorage` per user
- **Canvas Effects**: Run at ~20fps via `requestAnimationFrame` with hardware tier detection (GPU vs CPU)
- **Resource Management**: Effects pause when tab is not visible; canvas destroyed on theme switch

### Adding a New Theme
1. Add CSS variable overrides in `themes.css` under `[data-theme="newtheme"]`
2. Add theme name to `ThemeManager.THEMES` array in `theme.js`
3. Add `_initNewTheme()` and `_drawNewThemeFrame()` methods to `ThemeManager`
4. Add dispatch cases in `apply()` and `_startEffectLoop()`
5. Add cleanup in `_destroyCanvas()` for any state properties
6. Add theme option card in `settings.html` Display Preferences section
7. No bundle rebuild needed — `theme.js` is loaded standalone (not in `core.bundle.js`) for FOUC prevention; the `?v={{ config.APP_VERSION }}` cache-bust picks up the change on next version bump.

### Background Effects (Legacy)

#### Scanline Overlay
Applied via `body::after` - subtle repeating horizontal lines for CRT effect.

#### Canvas Effects
Each theme has a dedicated canvas effect rendered by `ThemeManager`:
- **Cyberpunk**: Simplex noise-based volumetric smoke with GPU hardware detection
- **Matrix**: Falling kanji/character columns
- **Ocean**: Moon reflection with wave physics simulation
- **Cathedral**: 60 golden dust motes with upward drift and divine light beam
- **Blade Runner**: 200 rain streaks with wind drift, 8% neon pink / 6% neon blue tinted
- **Elite 1984**: Vector-green starfield with stars streaming past at hyperspace speed

---

## 9. Quick Reference: Class Names

### Buttons
`btn`, `btn-primary`, `btn-secondary`, `btn-success`, `btn-warning`, `btn-danger`, `btn-sm`, `btn-lg`

### Forms
`form-group`, `form-label`, `form-input`, `form-select`, `toggle-switch`, `toggle-slider`

### Cards
`card`, `card-header`, `card-title`, `card-body`, `glass-card`

### Badges
`badge`, `badge-success`, `badge-warning`, `badge-danger`, `badge-purple`, `badge-secondary`

### Navigation
`sidebar`, `nav-section`, `nav-item`, `nav-icon`

### Tabs
`tool-tabs`, `tool-tab`, `system-tabs`, `system-tab`, `report-tabs`, `report-tab`, `settings-tabs`, `settings-tab`

### Layout
`app-container`, `main-content`, `content-wrapper`, `page-header`, `page-title`

---

## 10. JavaScript Standards

### API Response Format
```javascript
// Success
{ "success": true, "data": {...}, "message": "Optional message" }

// Error
{ "success": false, "error": "Error description" }
```

### Modal Dialogs (IMPORTANT)
**NEVER use browser `alert()` or `confirm()`.** Use custom modals:
```javascript
showModal('✓ Success', 'Operation completed.');
showConfirm('🗑️ Delete?', 'Are you sure?', () => { deleteItem(); });
```

### Event Handling
- Debounce search inputs: 300ms
- Throttle scroll events: 100ms
- Use event delegation for dynamic content

---

## 11. Accessibility

### Focus States
```css
element:focus-visible {
    outline: none;
    box-shadow: 0 0 0 2px rgba(76, 201, 240, 0.5);
}
```

### Color Contrast
- Minimum 4.5:1 for body text
- Minimum 3:1 for large text and UI components

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
    * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

---

## 12. Game Modals

### Overview
Game cards open modals instead of navigating to pages. Located in `base.html`.

### Detail Modal
- Class prefix: `.gdm-*`
- Open: `openGameDetailModal(gameId)`
- Caches up to 50 games

### Edit Modal
- Class prefix: `.gem-*`
- 6 tabs: quick, identity, release, gameplay, technical, description
- Genre/Controller use multi-select tag UI

### APIs
- Detail: `GET /api/game/<id>/detail`
- Edit: `POST /api/game/<id>/edit`

---

## 13. Toast Notifications

Global function defined in `static/js/utils.js`. Call as:

```javascript
showNotification('Message', 'success');  // Green
showNotification('Message', 'error');    // Red
showNotification('Message', 'info');     // Cyan
showNotification('Message', 'warning');  // Orange
showNotification('Auto-dismisses in 3s', 'info', 3000);  // 4th arg: duration in ms
```

Two related dialog primitives live in `templates/base.html` (so the CSP-nonce script-tag can inline them): `showConfirm(title, msg, onConfirm, opts?)` and `showModal(title, msg, onConfirm?, showCancel?, onCancel?)`. See CLAUDE.md "Non-Obvious JS / Template Contracts" for the full surface.

---

## 14. Bulk Operation Progress UI

Bulk operations (bulk scrape, PSN refresh, RA refresh, image resize, etc.) display progress in two places: a **modal** (foreground) and a **persistent toast** (background). Both follow the same layout convention.

### Progress Bar Layout

The progress bar divides information into two zones:

- **Above the progress bar** — what is currently **being processed** (present tense)
  - Game title (or file name) currently in progress
  - Counter showing which item we're on: `N / Total` where N = `processed + 1` (capped at total)
- **Below the progress bar** — what **has been processed** (past tense)
  - Status line: `Scraped 42 / 707 - 6%`
  - Result counters: Successful, Failed, Skipped

```
┌──────────────────────────────────────────┐
│  Game Title                    2 / 707   │  ← processing (current item)
│  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  ← progress bar
│  Scraped 1 / 707 - 0%                   │  ← processed (completed count)
│  ✅ 1    ❌ 0    ⏭️ 0                    │  ← result breakdown
└──────────────────────────────────────────┘
```

### Backend `processing` Field

The backend `get_status()` returns a `processing` field alongside `processed`:

- `processed` = `success_count + failed_count + skipped_count` (how many are done)
- `processing` = `min(processed + 1, total)` (which item number is currently active, 1-indexed, capped at total)

The frontend uses `data.processing` for the counter above the bar, and `data.processed` for the status line below. This avoids duplicating clamping logic across multiple JS consumers.

### Toast Detail Lines

Each job type can display contextual detail on separate lines — never concatenate multiple fields with dash separators:

| Job Type | Lines shown |
|----------|-------------|
| Bulk Scrape | System name (via `data.system_name`), then game title |
| PSN Refresh | Game title, then NPWR ID (via `data.current_npwr`) |
| RA Refresh | System name (via `data.current_system`), then game title |
| Image Resize | Image type folder (via `data.current_type`), then filename |

---

## 15. Glass Panel

For semi-transparent overlays with blur:
```css
.glass-panel {
    background: rgba(20, 28, 40, 0.9);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(76, 201, 240, 0.2);
}
```

---

## 16. System Type Badges

Color-coded pill badges indicating the platform type of a gaming system. Used on the dashboard, systems page, and settings page. All use 0.2 alpha background with matching border and text color.

**HTML Structure**:
```html
<span class="system-type-badge {{ system.system_type|lower }}">{{ system.system_type }}</span>
```

**Canonical class**: `.system-type-badge` (dashboard + settings). The legacy `.system-type-tag` class is still wired up in `templates/systems.html` for the systems page and JS-rendered cards within it; consolidating onto `.system-type-badge` is a known follow-up. Both follow the same color scheme.

| Class | Color | CSS Variable | System Type |
|-------|-------|-------------|-------------|
| `.console` | Cyan | `--primary-cyan` | Home consoles (NES, SNES, PlayStation, etc.) |
| `.handheld` | Green | `--neon-green` | Portable systems (Game Boy, PSP, DS, etc.) |
| `.computer` | Purple | `--neon-purple` | Home computers (C64, Amiga, DOS, etc.) |
| `.arcade` | Orange | `#f97316` | Arcade systems |
| `.engine` | Gold | `#eab308` | Game engines & frameworks (ScummVM, PICO-8, Doom, etc.) |

```css
.system-type-badge.console  { background: rgba(76, 201, 240, 0.2);  color: var(--primary-cyan); border: 1px solid rgba(76, 201, 240, 0.4); }
.system-type-badge.handheld { background: rgba(34, 197, 94, 0.2);   color: var(--neon-green);   border: 1px solid rgba(34, 197, 94, 0.4); }
.system-type-badge.computer { background: rgba(168, 85, 247, 0.2);  color: var(--neon-purple);  border: 1px solid rgba(168, 85, 247, 0.4); }
.system-type-badge.arcade   { background: rgba(249, 115, 22, 0.2);  color: #f97316;             border: 1px solid rgba(249, 115, 22, 0.4); }
.system-type-badge.engine   { background: rgba(234, 179, 8, 0.2);   color: #eab308;             border: 1px solid rgba(234, 179, 8, 0.4); }
```

---

## 17. Changelog Tags

Pill-shaped tags with `border-radius: var(--radius-full)` and `padding: 4px 12px`. All use 0.15 alpha background with solid border matching the text color.

| Class | Color | CSS Variable | Use For |
|-------|-------|-------------|---------|
| `.tag-feature` | Cyan | `--primary-cyan` | New user-facing features |
| `.tag-enhancement` | Green | `--neon-green` | Enhancements to existing features |
| `.tag-minor` | Purple | `--neon-purple` | Minor improvements, new options |
| `.tag-patch` | Orange | `--neon-orange` | Code quality, cleanup, refactoring |
| `.tag-fix` | Red | `--neon-red` | Bug fixes |
| `.tag-major` | Magenta | `--secondary-magenta` | Major releases, milestones |
| `.tag-ui` | Purple | `--neon-purple` | UI-only changes |
| `.tag-improvement` | Cyan | `--primary-cyan` | General improvements |
| `.tag-initial` | Magenta | `--secondary-magenta` | Initial release |

```css
.tag-feature     { background: rgba(76, 201, 240, 0.15);  border: 1px solid var(--primary-cyan);      color: var(--primary-cyan); }
.tag-enhancement { background: rgba(34, 197, 94, 0.15);   border: 1px solid var(--neon-green);        color: var(--neon-green); }
.tag-minor       { background: rgba(168, 85, 247, 0.15);  border: 1px solid var(--neon-purple);       color: var(--neon-purple); }
.tag-patch       { background: rgba(245, 158, 11, 0.15);  border: 1px solid var(--neon-orange);       color: var(--neon-orange); }
.tag-fix         { background: rgba(239, 68, 68, 0.15);   border: 1px solid var(--neon-red);          color: var(--neon-red); }
.tag-major       { background: rgba(247, 37, 133, 0.15);  border: 1px solid var(--secondary-magenta); color: var(--secondary-magenta); }
.tag-ui          { background: rgba(168, 85, 247, 0.15);  border: 1px solid var(--neon-purple);       color: var(--neon-purple); }
.tag-improvement { background: rgba(76, 201, 240, 0.15);  border: 1px solid var(--primary-cyan);      color: var(--primary-cyan); }
.tag-initial     { background: rgba(247, 37, 133, 0.15);  border: 1px solid var(--secondary-magenta); color: var(--secondary-magenta); }
```

---

## 18. Number Formatting

### Thousand Separators
All numeric values displayed in the UI must use **thin space** as the thousand separator. Never use commas.

| Raw Value | Displayed As |
|-----------|-------------|
| `1000` | `1 000` |
| `723415` | `723 415` |
| `42` | `42` |

### Jinja2 Templates
Use the `|format_number` template filter:
```html
{{ stats.total_games|format_number }}
{{ (score_stats.games_with_critic or 0)|format_number }}
```

### JavaScript
Use the global `formatNumber()` function from `utils.js`:
```javascript
formatNumber(12573)  // → "12 573"
```

### Ratios (X / Y)
Whenever a number is shown as a ratio, use spaces around the slash: `X / Y`, never `X/Y`.

**Jinja2:**
```html
{{ earned|format_number }} / {{ total|format_number }}
```

**JavaScript:**
Use the global `formatRatio()` function from `utils.js`:
```javascript
formatRatio(earned, total)  // → "1 234 / 5 678"
```

Or manually:
```javascript
`${formatNumber(earned)} / ${formatNumber(total)}`
```

### What NOT to Format
- Percentages (e.g., `85%`)
- IDs, loop indices, boolean flags
- File paths, CSS values
- Scores out of 100 (e.g., `85 / 100` — use spaces around slash but no thousand separator needed)
- Player counts (1–4)

---

## 19. Date Formatting

### Standard Display Format
All dates use **ISO 8601 hyphen separators** (`-`). Display matches storage — no conversion needed.

| Context | Format | Example |
|---------|--------|---------|
| Date only | `YYYY-MM-DD` | `1996-09-29` |
| Date + time | `YYYY-MM-DD HH:MM:SS` | `2024-03-15 14:30:00` |
| Year only (tags, cards) | `YYYY` | `1996` |

### Storage = Display
- **Database storage**: `YYYY-MM-DD` (ISO 8601)
- **User-facing display**: `YYYY-MM-DD` (same as storage — no conversion)
- **HTML date inputs**: `YYYY-MM-DD` (HTML spec, matches display)
- **Log file content**: `YYYY-MM-DD HH:MM:SS`
- **Date input mask**: Auto-inserts `-` after year and month

### Implementation

#### Jinja2 Templates
```jinja
{# Full date from DB field — use directly, no conversion #}
{{ game.release_date if game.release_date else '' }}

{# Date from ISO timestamp #}
{{ timestamp.replace('T', ' ')[:19] }}

{# Python strftime #}
{{ date_obj.strftime('%Y-%m-%d %H:%M:%S') }}
```

#### JavaScript
```javascript
// DB date string — use directly, no conversion needed
game.release_date

// Date object → display (use DateUtils from utils.js)
DateUtils.formatDate(dateObj)  // → "2024-03-15"

// Timestamp → display
date.toISOString().slice(0, 19).replace('T', ' ')  // → "2024-03-15 14:30:00"
```

#### Python (server-side formatting for templates)
```python
datetime_obj.strftime('%Y-%m-%d %H:%M:%S')
```

### What NOT to Convert
- No conversion is needed anywhere — display format matches storage format
- API JSON responses use ISO format which is the same `YYYY-MM-DD`
- The `routes/games.py` edit handlers keep a `'/' in value` safety net to handle old bookmarks or manual slash input

---

## 20. CSS Architecture

### Overview

RetroDB uses a **modular CSS system**. All styles are split into individual files under `static/css/` and concatenated into `main.min.css` by `build_css.py`. The canonical load order is the `CSS_ORDER` list in `build_css.py`; `static/css/main.css` is a maintained `@import` chain that mirrors that order for local development. The base template (`templates/base.html`) loads only `main.min.css`.

### File Structure & Load Order

```
static/css/
├── core/               # 1. CORE — loaded first
│   ├── variables.css   #    CSS custom properties (:root)
│   ├── reset.css       #    Browser reset / normalize
│   └── typography.css  #    Font faces, heading hierarchy
├── layout/             # 2. LAYOUT
│   ├── layout.css      #    Page grid, main content area
│   ├── sidebar.css     #    Sidebar navigation
│   └── responsive.css  #    Media queries (loaded LAST)
├── components/         # 3. BASE COMPONENTS — reusable UI primitives
│   ├── buttons.css     #    .btn, .btn-primary, .btn-danger, etc.
│   ├── forms.css       #    .form-group, .form-input, .form-select, toggles
│   ├── cards.css       #    .card, .card-header, .card-body
│   ├── badges.css      #    .badge, .badge-success, etc.
│   ├── tables.css      #    .data-table, thead/tbody styling
│   ├── tabs.css        #    Tab component base styles
│   ├── modals.css      #    .modal, .modal-content, confirm dialogs
│   ├── toasts.css      #    Toast notification system
│   ├── progress.css    #    Progress bars, loading states, rate-limit cards
│   ├── tags.css        #    Tag/chip components
│   ├── queue-manager.css  # Scrape queue manager component
│   └── launch-indicator.css  # Launch-state indicator chip
├── features/           # 4. FEATURES — domain-specific compound components
│   ├── game-cards.css  #    Game card grid and card internals
│   ├── game-modals.css #    Game detail/edit modal system
│   ├── trophies.css    #    Trophy display components
│   ├── achievements.css #   Achievement display components
│   ├── stat-boxes.css  #    Stat box / summary card grids
│   ├── filters.css     #    Filter bar and filter controls
│   └── hltb.css        #    HowLongToBeat integration styles
├── pages/              # 5. PAGES — page-specific layout rules
│   ├── pages.css       #    Settings, Reports, Changelog, Login, Help, etc.
│   └── game-list.css   #    Game list / library page specifics
├── effects/            # 6. EFFECTS
│   ├── backgrounds.css #    Mist/fog, scanlines, gradient backgrounds
│   └── animations.css  #    Keyframe animations, transitions
├── utilities.css       # 7. UTILITIES — last (for override capability)
├── main.css            # Development entry point (@import chain mirrors build_css.py CSS_ORDER)
└── main.min.css        # Production bundle (built by build_css.py)
```

### Where to Put Styles

| Style type | Location | Examples |
|---|---|---|
| **CSS variables** | `core/variables.css` | Colors, spacing, fonts, shadows |
| **Reusable UI primitives** | `components/*.css` | Buttons, forms, cards, badges, progress bars, modals, tables |
| **Domain-specific compound components** | `features/*.css` | Game cards, trophy displays, achievement grids, stat boxes |
| **Page-specific layout** | `pages/*.css` | Tab arrangements, page headers, section ordering that only apply to one page |
| **Animations & keyframes** | `effects/animations.css` | Shared keyframes and transition definitions |
| **Utility classes** | `utilities.css` | `.text-success`, `.d-flex`, `.mb-lg`, spacing/display/text helpers |
| **Media queries** | `layout/responsive.css` | All breakpoint overrides |

### Rules

1. **No inline `<style>` blocks in templates** for styles that are reusable or already exist in external CSS. If a class could conceivably be used on more than one page, it belongs in the external CSS.
2. **Inline `<style>` blocks are acceptable ONLY for** truly page-unique styles that have no reuse potential (e.g., a one-off animation for a specific page). These should be rare and minimal.
3. **Never duplicate classes** that already exist in the external CSS. Common offenders: `.text-success`, `.text-warning`, `.text-danger`, `.form-group`, `.form-input`, `.page-header`, `.stat-box`, `.progress-bar`, `.loading-spinner`.
4. **After adding or modifying any external CSS file**, rebuild the production bundle:
   ```bash
   python3 build_css.py
   ```
5. **If adding a new CSS file**, add it to both `main.css` (in the correct section) and `build_css.py` (`CSS_ORDER` list — the canonical source of truth) at the same position.
6. **Load order matters**: Variables → Reset → Typography → Layout → Components → Features → Pages → Effects → Utilities → Responsive. Later files can override earlier ones. Utilities load near-last intentionally.

### Decision Flowchart

```
Is this style used on 2+ pages?
  YES → External CSS file (components/ or features/)
  NO  → Is it a variant of an existing component?
          YES → Add to that component's CSS file
          NO  → Is it page-specific layout?
                  YES → pages/*.css
                  NO  → Inline <style> (with comment explaining why)
```

---

## 21. Version & Changelog Policy

**Every code change must include a version bump and changelog entry.** This is not optional and should never require a user prompt.

### When to Update
- After completing any task that modifies source files (templates, CSS, JS, Python, config)
- Before considering the work "done"

### Steps (always perform both)
1. **Bump `APP_VERSION`** in `config.py` and set `APP_LAST_UPDATE` to today's date
   - Patch bump (x.x.**N+1**) for bug fixes, cleanup, accessibility, refactoring
   - Minor bump (x.**N+1**.0) for new features, enhancements
   - Major bump (**N+1**.0.0) for major releases, breaking changes
2. **Add a changelog entry** at the top of `data/changelog.yaml` with:
   - `version`, `date` (YYYY-MM-DD — matches the on-disk format), `tags` (type: feature/minor/patch), and `body` (HTML summary)

### Changelog Tag Types
| Tag | Use For |
|-----|---------|
| `feature` | New user-facing features |
| `enhancement` | Enhancements to existing features |
| `minor` | Minor improvements, new options |
| `patch` | Code quality, cleanup, refactoring, accessibility |
| `fix` | Bug fixes |
| `major` | Major releases, milestones |
| `ui` | UI-only changes |
| `improvement` | General improvements |
| `initial` | Initial release |

---

## 22. Security Standards

### Route Authentication
- **All routes must have an auth decorator** — `@login_required` at minimum for read access, `@editor_required` for write operations, `@admin_required` for admin functions.
- Public exceptions: login page, setup wizard, static files, dashboard, and analytics (read-only public views).
- Import decorators from `services.auth`: `login_required`, `editor_required`, `admin_required`, `permission_required`.

### File Path Validation
- **Never pass user-supplied filenames or paths directly to filesystem operations.**
- Use `safe_filename(filename)` from `services/security.py` for any user-supplied filename (log files, screenshots, backup files). Returns `None` if unsafe.
- Use `safe_path(user_path, allowed_base)` from `services/security.py` for any user-supplied directory or file path. Resolves symlinks and verifies the path stays within the allowed base directory. Returns `None` if unsafe.
- Always check the return value — if `None`, return a 400 error to the client.

### JavaScript XSS Prevention
- **Always use `escapeHtml()` (from `utils.js`) when inserting server data into `innerHTML`.**
- Use `encodeURIComponent()` for dynamic values in URL attributes (`src`, `href`).
- Use `encodeURI()` for full URL values.
- Never construct HTML strings with unescaped template literals from API responses.

### Error Message Sanitization
- **Never return `str(e)` to the client** in error responses — exception messages may leak internal paths, database schema, or stack traces.
- Log the actual error with `logger.error(f"Operation failed: {e}")`.
- Return a generic message: `jsonify({'success': False, 'error': 'An internal error occurred'}), 500`.

### SQL Injection Prevention
- **Always use parameterized queries** with `?` placeholders — never use f-strings or string concatenation for SQL.
- This is already followed throughout the codebase. Maintain this standard for all new code.

### Session & Cookie Security
- Session cookies are configured with `HttpOnly=True` and `SameSite=Lax` in `app.py`.
- `SameSite=Lax` prevents cross-origin POST requests from sending session cookies, serving as the primary CSRF defense.
- `Secure=True` is env-gated via `RETRODB_SECURE_COOKIES` (default off). Operators fronting RetroDB with a TLS reverse proxy should set this to `true`; leaving it off on a localhost HTTP deploy avoids silently breaking login (the browser would refuse to send the cookie over plain HTTP).
- Do not override these settings in route code.

### CSRF Protection
- RetroDB ships a **custom CSRF implementation** (see `app.py::validate_csrf` / `before_request`) rather than `Flask-WTF` / `CSRFProtect`. The impl is HMAC + per-session token stored in `session['_csrf_token']`, validated against `X-CSRF-Token` header or `_csrf_token` form field on every state-changing request, with an explicit exempt set for login / setup / static.
- **Design intent** (why not Flask-WTF): the custom implementation is ~30 lines with zero extra dependencies, and the deployment target is a single-user localhost app where CSRF is low-impact even without the token (the `SameSite=Lax` cookie is already the primary defence). Flask-WTF would add `wtforms` + `itsdangerous` pins for no additional protection and would require migrating every existing `_csrf_token` form field. A future contributor considering a switch to `CSRFProtect` should first confirm the migration cost is worth the ergonomics, not just assume the stdlib-built version is ad-hoc.

### Security Headers
- The following headers are set on every response via `@app.after_request` in `app.py`:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Future recommendation**: Add a Content Security Policy (CSP) header once inline styles/scripts are refactored to external files.

### Login Security
- Minimum password length: 8 characters.
- Login rate limiting: 5 failed attempts per IP within 5 minutes triggers a lockout (429 response).
- Rate limiting functions are in `services/security.py`: `rate_limit_login(ip)`, `record_login_attempt(ip, success)`.

---

## 23. Controller Naming Standards

### Naming Format
Controllers follow a strict naming convention based on their type:

| Type | Format | Example |
|------|--------|---------|
| **Standard Controller** | `Name (Model)` | `DualShock 2 (SCPH-10000 to SCPH-10440 series)` |
| **Computer Keyboard** | `[System] Integrated Keyboard (Built-In)` | `Amstrad CPC Integrated Keyboard (Built-In)` |
| **Handheld Controls** | `[System] Built-In Controls (Model)` | `Game Boy Advance Built-In Controls (AGB-001)` |
| **Peripheral** | `Name (Model)` | `NES Zapper (NES-005)` |
| **3rd Party** | `Name (Model)` | `Hori Fighting Commander (HPS-09)` |

### Rules
1. **Model numbers** are always in parentheses after the name
2. **Multiple model numbers** are separated by ` / ` (space-slash-space): `(HSS-0101 / MK-80100 / MK-80116)`
3. **Capitalisation**: Every word capitalised, "Built-In" always has capital I
4. **No system prefix** on standard/3rd party controllers — the system association is handled by the `system_controllers` junction table
5. **System prefix required** only for integrated keyboards and built-in handheld controls
6. **`is_default` flag**: Set to `1` on pack-in / standard controllers that shipped with the system. These are used as the default controller name in AI metadata fill and game detail views
7. **3rd party controllers**: Only include genuinely popular/well-known controllers — not every budget clone
8. **USB / Bluetooth Keyboard**: Use this generic name (no model number) for modern systems that support standard keyboards

### Manufacturer Field
- Use the common company name: `Hori`, `Logitech`, `Mad Catz`, `Namco`, `Nacon`, `Razer`, `Scuf`
- For first-party: `Sony`, `Microsoft`, `Nintendo`, `Sega`, `Atari`, `SNK`

---

## 24. Code Naming Standards

These rules codify conventions already in use across the codebase.  New
modules, classes, functions, and files must follow them; existing code that
deviates should be migrated when touched (see `roadmap.md`).

### 24.1 Python

| Artefact | Convention | Example |
|----------|-----------|---------|
| Module files | `snake_case.py` | `services/api_helpers.py`, `routes/games_hltb.py` |
| Packages | `snake_case/` | `services/`, `scraper/`, `services/jobs/` |
| Classes | `PascalCase` | `BulkScrapeJob`, `SecretRedactor`, `HLTBLookup` |
| Functions / methods | `snake_case` | `get_current_user()`, `apply_metadata_to_game()` |
| Variables | `snake_case` | `game_id`, `match_confidence` |
| Module-level constants | `SCREAMING_SNAKE_CASE` | `ROLE_PERMISSIONS`, `MANUFACTURER_MAP`, `COMPUTER_SYSTEMS` |
| Module-private helpers | `_leading_underscore` | `_extract_alt_titles()`, `_apply_pending_match()` |
| Decorators | `snake_case`, verb-phrase | `@login_required`, `@admin_required`, `@handle_api_errors` |
| Test files | `test_<subject>.py` | `test_alternate_titles.py`, `test_routes_smoke.py` |
| Test functions | `test_<behaviour>` | `def test_alt_titles_empty_input(): ...` |

**Module naming within a package:**
- Route blueprints live in `routes/<subject>.py` (e.g. `routes/games.py`,
  `routes/trophies.py`).  When a route file is split, suffix with the
  sub-subject: `routes/games_hltb.py`, `routes/games_ai.py`,
  `routes/games_search.py`, `routes/games_media.py`.
- Scrapers live in `scraper/scrape_<source>.py` — one word per source, no
  `scrape_metadata_` prefix (all scrapers scrape metadata; the prefix adds
  nothing).  Examples: `scrape_igdb.py`, `scrape_rawg.py`, `scrape_steam.py`.
  Shared scraper infrastructure (not tied to one source) is named by role:
  `base_scraper.py`, `hybrid_scraper.py`, `scraper_manager.py`,
  `metadata_merger.py`.
- Service modules in `services/<role>.py` are named after the role, not the
  subject — `services/database.py`, `services/auth.py`,
  `services/formatters.py`, `services/template_filters.py`.
- Background jobs in `services/jobs/<job>.py` are named by the job verb:
  `bulk_scrape.py`, `ra_sync.py`, `image_resize.py`, `hltb_bulk.py`.

### 24.2 JavaScript

| Artefact | Convention | Example |
|----------|-----------|---------|
| Files | `kebab-case.js` | `game-modals.js`, `toast-controller.js`, `all-games-controller.js` |
| Exported singletons / controllers | `PascalCase` | `BulkScrapeController`, `FanartController`, `GameDetailModal`, `TrophySync` |
| Exported utility objects | `PascalCase` | `API`, `Storage`, `Notifications`, `DOM`, `DateUtils`, `StickyScroll` |
| Functions | `camelCase` | `showNotification()`, `formatBytes()`, `gameDetailUrl()` |
| Variables | `camelCase` | `const gameId = ...`, `let matchConfidence = ...` |
| Module-level constants | `SCREAMING_SNAKE_CASE` | `NOTIFICATION_TIMEOUTS` |
| Module-private | `_leading_underscore` | `_MODAL_RATING_COLS`, `_getAllRatingsFromGame()` |

**File naming within `static/js/`:**
- Bundled files (see `build_js.py`): short, functional names — `utils.js`,
  `main.js`, `filters.js`.
- Page-specific files: noun or noun-phrase — `achievements.js`,
  `trophies.js`, `museum.js`, `log-viewer.js`, `rom-tools.js`.
- Controllers bound to a page feature: noun + `-controller` —
  `all-games-controller.js`, `toast-controller.js`.

### 24.3 CSS

| Artefact | Convention | Example |
|----------|-----------|---------|
| Files | `kebab-case.css` | `game-cards.css`, `queue-manager.css`, `stat-boxes.css` |
| Class names | `kebab-case`, BEM-ish | `.btn-neon`, `.card-glass`, `.game-card__title`, `.is-active` |
| CSS custom properties | `--kebab-case` | `--primary-cyan`, `--bg-darkest`, `--font-heading` |

File placement rules are in §20 (CSS Architecture).

### 24.4 Templates

| Artefact | Convention | Example |
|----------|-----------|---------|
| Files | `snake_case.html` | `game_detail.html`, `local_trophy_detail.html` |
| Partials / macros | `_leading_underscore.html` | `_bulk_scrape_modal.html`, `_bulk_edit_modal.html` |
| Jinja macros | `snake_case` | `{% macro rating_badge(system, value) %}` |

Partials and macros should go under `templates/_partials/` or
`templates/_modals/` (to be introduced in Pass 9 — see `roadmap.md`).

### 24.5 Database

| Artefact | Convention | Example |
|----------|-----------|---------|
| Tables | `snake_case`, plural | `games`, `systems`, `hltb_pending_matches` |
| Columns | `snake_case` | `system_id`, `playtime_estimate`, `hltb_match_confidence` |
| Junction tables | `<a>_<b>` | `system_controllers`, `game_tags` |
| Foreign keys | `<table_singular>_id` | `game_id`, `system_id`, `user_id` |
| Boolean flags | `is_<adj>` or `has_<noun>` | `is_default`, `has_manual` |

### 24.6 Changelog / version artefacts

See §21 for tag types.  Entries in `data/changelog.yaml` use `type`
values from a fixed set (`enhancement`, `fix`, `chore`, `security`, etc.);
see §17 for the full list.

### 24.7 When to rename

- **Free to rename**: module-private helpers (`_leading_underscore`),
  unused functions, local variables.
- **Rename with care**: public functions / classes imported across files
  (grep callers first, update all in the same commit).
- **Rename with user sign-off**: anything referenced from templates or JS
  bundles (e.g. a Python function exposed via a Jinja filter, or a JS
  singleton whose name appears in template inline scripts).
- **Never silently rename**: DB columns, route URLs, JSON response field
  names — these are external contracts.

---

## 25. Schema Migrations

Schema and one-shot data changes go through the versioned migration runner
in `services/migrations/__init__.py`, driven by SQLite's `PRAGMA
user_version`. Every migration is run at most once per install.

### 25.1 Authoring a migration

1. Create `services/migrations/scripts/NNN_short_description.py` where
   `NNN` is the next zero-padded number (currently `004_…` is next).
2. The module must expose a single function:
   ```python
   def apply(conn):
       cursor = conn.cursor()
       cursor.execute("ALTER TABLE games ADD COLUMN ...")
   ```
   `conn` is a raw `sqlite3.Connection`. Don't open or close it; don't
   commit (the runner owns the transaction).
3. Append the module's stem to `MIGRATIONS` in
   `services/migrations/__init__.py`. The 1-indexed position becomes the
   `user_version` the DB advances to after the migration runs.

### 25.2 Idempotency

Every migration must be safely re-runnable on a database that already
carries the change — pre-versioned installs may have been built up by the
old `_migrate_*` pattern and now sit at `user_version = 0` with the
schema already in its post-migration state.

- Tables: `CREATE TABLE IF NOT EXISTS`.
- Columns: wrap `ALTER TABLE ADD COLUMN` in `try / except
  sqlite3.OperationalError: pass` (SQLite has no `ADD COLUMN IF NOT
  EXISTS`).
- Indexes: `CREATE INDEX IF NOT EXISTS`.
- Data updates: write `WHERE` clauses that no-op on already-converted
  rows (e.g. `WHERE pegi_rating = '12'` rather than blind `UPDATE …`).

### 25.3 Append-only invariant

Once a migration ships in a tagged release, it is frozen:

- **Never edit the body** of a shipped migration. Production DBs have
  already run it; edits will not retroactively apply.
- **Never reorder or delete** entries in `MIGRATIONS`. The list index is
  the version number. Reordering would advance some DBs into an
  inconsistent state on next startup.
- Schema typos and bugs are corrected by **adding a new migration** that
  fixes them.

### 25.4 Transactions and failure handling

Each migration runs inside its own `BEGIN`/`COMMIT` along with the
matching `PRAGMA user_version = N`. If a migration raises, the runner
calls `ROLLBACK` so the DB stays at the previous version with no partial
DDL. The exception bubbles up so the caller (and any service-management
layer like systemd) sees the failure.

### 25.5 Testing

`tests/test_migrations.py` covers fresh installs, legacy installs, the
no-op fast-path, rollback on failure, and the
"DB-newer-than-build" guard. New migrations don't typically need
dedicated tests — but data migrations with non-trivial transformations
(e.g. genre normalization) should add a regression check that exercises
the rewrite logic against representative fixtures.

---

*Document Version: 2.5.0*
*Last Updated: 2026-04-23*
