# Premium web design direction

The public site and application share an original orbital-routing visual identity.
The reference site's request returned a network proxy 403; no reference assets,
copy, logos or layouts were downloaded. The user's supplied brief is the design input.

## Tokens and layout

- Void `#06080d`: public canvas and application background.
- Graphite `#10151f`: working surfaces, separated with restrained cool borders.
- Porcelain `#f3f6fc`: primary typography; mist `#a8b3c7`: secondary information.
- Signal blue `#5089ff`: actions, focus and selected routes.
- Steel `#8797b8`: structural lines; restrained mint/amber/red indicate data states.
- Manrope: locally bundled variable display/body face, selected for open counters
  and strong large-scale geometry. System fallbacks keep offline startup usable.
- Marketing: left-aligned oversized headline and an original SVG refractive orbit
  occupying the right side; lower sections explain the actual decision workflow.
- Application: fixed 232px sidebar, calm header, compact KPI rail, asymmetric
  analysis panels and readable paginated tables. Mobile uses an accessible drawer.

```text
Marketing:  [brand          navigation          launch]
            [large title + CTA       original routing lens]
            [capabilities / actual live demo preview / architecture / footer]

Platform:   [sidebar] [header + shared dataset controls]
                     [page heading + actions]
                     [computed metrics / plots / tables / task forms]
```

## Review against the brief

Keep the cinematic object in the hero rather than repeating gradients on every
card. Use a distinct application information density, not a landing-page card
grid as a dashboard. No fake customer logos, live-network claims, invented KPI
growth or unverified savings. A single restrained hero animation respects reduced
motion; user-triggered state changes receive short feedback. All platform menu
items are real App Router routes. Empty/error/loading states are working states.

## Implementation boundaries

Next.js/React/TypeScript, Tailwind, local shadcn-style Radix primitives, Lucide,
Recharts and Motion. FastAPI adapters call existing Python functions. New SQLite
workspace/run tables are separate from the existing case history database.
Marketing preview metrics also come from the API and are labeled Synthetic Demo.
