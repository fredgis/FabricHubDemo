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
