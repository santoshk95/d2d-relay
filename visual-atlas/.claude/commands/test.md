---
description: Build and test the visuals in the mock Power BI host, then review the screenshots
---
1. Run `docker run --rm -v "$PWD":/work -w /work visual-atlas make build test` (build the image first if needed: `docker build -t visual-atlas -f docker/Dockerfile .`).
2. Read the output: every `RESULT` line must say `pass` and the run must end with `ALL CHECKS PASSED`.
3. Open and look at `visuals/test/out/cols_test.png` and `visuals/test/out/flow_test.png` (and any new family's screenshot). Check for clipped or overlapping labels, wrong colors, broken layouts in dark mode or high contrast, and empty cases.
4. Summarize what passed, what failed and what looks wrong, and fix it if asked.
$ARGUMENTS
