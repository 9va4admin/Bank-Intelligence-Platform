# Frontend Rules (React · Theming · Component Standards)

## Multi-Theme Requirement (Non-Negotiable)

Every new React page component that renders visible UI **must** support both dark and light themes.
This is not optional — bank operators may prefer a lighter UI in bright office environments.

### Mandatory Pattern

```jsx
// 1. Import useTheme at the top of every page component file
import { useTheme } from '../../../shared/theme/ThemeContext'  // adjust path depth as needed

// 2. Call the hook at the top of the component body (before any early returns)
export default function MyPage() {
  const { isDark } = useTheme()

  // 3. Define a th (theme helper) object — ALL structural colour classes go here
  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
  }

  // 4. Use th.* everywhere — never hardcode dark classes in JSX
  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <h1 className={`text-lg font-semibold ${th.heading}`}>Page Title</h1>
        ...
      </div>
    </AppShell>
  )
}
```

### Dark → Light Class Mapping Reference

| Dark class | Light equivalent |
|---|---|
| `bg-navy-950` / `bg-[#020817]` | `bg-slate-50` |
| `bg-navy-900` | `bg-white` |
| `bg-white/5` / `bg-white/2` | `bg-white` / `bg-slate-50` |
| `text-white` / `text-slate-100` | `text-slate-900` |
| `text-slate-300` | `text-slate-700` |
| `text-slate-400` | `text-slate-500` |
| `text-slate-500` | `text-slate-400` |
| `text-slate-600` | `text-slate-400` |
| `border-white/8` | `border-slate-200` |
| `border-white/5` | `border-slate-100` |
| `hover:bg-white/2` | `hover:bg-slate-50` |

### Sub-Components That Receive isDark

When a page has sub-components (e.g. `<DetailPanel>`, `<ReviewPanel>`), pass `isDark` as a prop
and apply the same pattern inside the sub-component. Do not call `useTheme()` inside sub-components
unless they are used standalone in multiple places.

```jsx
function DetailPanel({ item, isDark }) {
  const th = { heading: isDark ? 'text-white' : 'text-slate-900', ... }
  return <div className={th.heading}>...</div>
}
```

### Dual Badge / Status Pill Classes

For severity or status badges that use background+text combos that vary significantly between
dark and light modes, define separate objects and select by `isDark`:

```jsx
const SEV_D = { CRITICAL: 'bg-red-900/60 text-red-300 border-red-700/50', ... }
const SEV_L = { CRITICAL: 'bg-red-100 text-red-700 border-red-300', ... }
const SEV = isDark ? SEV_D : SEV_L
```

### What Does NOT Need Theming

- Data visualisation accent colours (chart bars, line colours, progress fills) — keep fixed
- Severity / status badge hues (red = critical, amber = warning) — keep hue, adjust shade
- Icon colours (`text-emerald-400`, `text-red-400`, `text-violet-400`) — these are semantic

### Shell Wrappers

- CTS pages: wrap with `<AppShell>` — already theme-aware, handles sidebar + topbar
- EJ pages: wrap with `<EJShell>` — already theme-aware, handles topbar

### ThemeContext API

```
ThemeContext.jsx exports:
  useTheme()  →  { theme: 'dark'|'light', toggle: () => void, isDark: boolean }
  ThemeProvider  →  wraps the app, persists to localStorage('astra-theme')
```

The theme toggle button is in `AppShell` (CTS) and `EJShell` (EJ). No page needs to render its own toggle.

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Every new page uses `useTheme()` | Code review: pages without `useTheme` import on PR flagged HIGH | PR merge |
| No hardcoded dark class on page wrapper div | Semgrep pattern: `className="bg-\[#020817\]"` or `className="bg-navy-950"` outside shell files | PR merge blocked |
| `th` object defined before JSX return | Code review: colour classes inline in JSX without `th.` prefix flagged MEDIUM | PR merge |
| Sub-components receive `isDark` prop | `security-auditor` agent review when DetailPanel-pattern components lack prop | PR merge |
| Both dark and light manually verified | Developer checklist: toggle theme in browser before raising PR | PR description required |
