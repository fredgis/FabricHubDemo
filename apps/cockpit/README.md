# MSFlix Business Control

Cinematic, authenticated entertainment-business controls on Rayfin/Fabric.
Real licensed film metadata, actual fictional-identity Salesforce records,
persisted rentals/purchases, playback rights and a transactional outbox.

See [the cockpit runbook](../../docs/COCKPIT.md) for live URLs, exact app-linked
SQL coordinates, native caller verification gate, publisher contracts and
actual acceptance evidence.

## Local checks

```powershell
npm run build:fabric
npm run lint
npm test
```

`npm run dev` starts only a loopback Vite frontend against the active deployed
backend. It does **not** deploy to a default workspace. Mock local login is
removed. Fabric's supported portal broker is required for end-user auth.

## Data Flow

Open **Data Flow** in the navigation, or `/dataflow` after authentication.
The English explorer is preserved in `src/assets/msflix-dataflow-en.html`,
including its shared Gold diagram, inventory, source filters, processing steps,
search, dialogs, light/dark themes, and PNG/JPEG/WebP/SVG exports.

It is a repository snapshot, not a live service monitor or an additional Gold
query. Its original wording and snapshot references are intentionally unchanged.
The document is loaded only on first visit in a CSS-isolated iframe; returning
to it preserves its selection, search, scroll and theme. **Refresh data flow**
resets only that document, without refreshing other cockpit reads.
**Expand view** hides the sidebar for the full-width diagram; **Restore navigation**
returns to the normal shell. Narrow viewports retain the original source-route
layout. The iframe runs the trusted, versioned document; it is not a sandbox for
untrusted HTML.

## Deployment and imports

```powershell
# Full rayfin up, after validating exact MSFlix workspace/capacity from binding.
npm run rayfin:up

# Rerunnable actual-data imports, no source credentials accepted.
node tools/manage.mjs --binding tools/binding.live.local.json `
  --catalog ../../data/catalog.json `
  --customers ../../.state/salesforce/customers.json `
  --campaigns ../../.state/salesforce/campaigns.json `
  --offer-policy tools/offers.policy.json
```

Create the binding only from actual app `userDbInfo` and SQL item coordinates.
`tools/binding.example.json` intentionally refuses deployment/import until
validated. Live coordinates and acceptance command inputs are git-ignored.
Never commit secrets or tokens.

## Brand

Background `#121315`, panels `#1B1C1F`, text `#F1F0EE`, muted `#B2B1B5`,
borders `#34353A`, accent `#ED6757`, focus/hover `#F39489`.
Logo wording: **MSFLIX**, with silver MS and vermilion FLIX, subtitle
**BUSINESS CONTROL**. Typography uses local Segoe UI Variable / Segoe UI.
