---
description: Package the Atlas custom visuals into release/ (in Docker)
---
Build the custom visuals:

1. If the `visual-atlas` Docker image doesn't exist (`docker image inspect visual-atlas`), build it: `docker build -t visual-atlas -f docker/Dockerfile .`
2. Run `docker run --rm -v "$PWD":/work -w /work visual-atlas make build` (on Windows PowerShell use `-v "${PWD}:/work"`).
3. Report the `.pbiviz` files written to `release/` and any ESLint or TypeScript errors. Fix errors in `visuals/common/` (shared) or the visual's own `src/`, never in `src/common/` copies.
$ARGUMENTS
