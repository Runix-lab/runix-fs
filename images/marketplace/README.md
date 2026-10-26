# Runix FS Marketplace assets

The logo vector is reused unchanged from the existing Runix website source:
`cuihuan/runix-site/assets/logo.svg`. No competitor brand asset is used.

- `runix-logo-320.png`: 320 x 320 transparent logo for the product thumbnail.
- `runix-fs-overview-780x439.png`: opaque 780 x 439 product-preview artwork.
- Matching SVG files are editable sources, not screenshots of a live service.

The preview explicitly says commercial onboarding is in preparation. It makes
no SLA, capacity, performance, public-availability or working-console claim.
Keep that disclosure until end-to-end delivery and public visibility are proved.
This is generic product artwork, not the private infrastructure diagram required
for AWS architecture review. Do not upload private network/account details.

Render with Node.js and the existing `sharp` dependency:

```sh
node scripts/runix/render_marketplace_assets.cjs
python -m unittest discover -s scripts/runix -p 'test_marketplace_assets.py'
```

In the Codex local runtime, use its bundled Node package directory in NODE_PATH.
No new dependency or package manifest is added to the engine workspace.
Asset tests check dimensions, opaque gallery output, disclosure/attribution and
the absence of executable/external SVG dependencies. Visually inspect the PNG
after text/layout changes. The preview was visually inspected on 2026-10-26.
