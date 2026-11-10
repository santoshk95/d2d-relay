# Power BI report-theme schema

`reportThemeSchema.json` is Power BI's own JSON schema for report themes, version **5.78**, taken from Power BI Desktop
2.159.883.0 (October 2026): `bin\WebView2Resources\minerva\scripts\desktop.reportThemeSchema.json.min.js`. Microsoft
also publishes it under the MIT licence in `microsoft/powerbi-desktop-samples` ("Report Theme JSON Schema").

`genbi_kit/stock.py` reads it for every formatting object and property of Power BI's built-in visuals (the Format
pane): the visual's own objects (`definitions/visual-<type>`) and the container objects every visual shares
(`definitions/commonCards`: title, subTitle, background, border, dropShadow, padding, visualHeader, visualTooltip …),
with their types and allowed values.

## Refresh it after a Power BI Desktop update

```bash
node genbi_kit/schemas/powerbi/extract_theme_schema.js "C:/Program Files/Microsoft Power BI Desktop/bin/WebView2Resources/minerva/scripts/desktop.reportThemeSchema.json.min.js" genbi_kit/schemas/powerbi/reportThemeSchema.json
```

The script prints the schema version and the visuals it covers; update `SCHEMA_VERSION` in `stock.py`, then run
`tests/stock_visuals_test.py` (it checks the gallery against the new schema). Field wells (data roles) are not in this
schema: they are listed in `stock.SPECS`, from Desktop's visual capabilities and Microsoft's PBIR references.
