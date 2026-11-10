# Power BI notes (checked facts)

These facts were checked against Microsoft Learn, Microsoft's GitHub samples, or the SDK typings in `node_modules/powerbi-visuals-api/src/visuals-api.d.ts`. Where something is an inference, it says so.

## Toolchain

| Package | Version | Notes |
|---|---|---|
| powerbi-visuals-tools (pbiviz) | 7.2.1 | `pbiviz new`, `pbiviz package` (runs ESLint + webpack; packaging needs no certificate) |
| powerbi-visuals-api | 5.11.1 | `apiVersion` in pbiviz.json |
| powerbi-visuals-utils-formattingmodel | 6.0.4 | Format pane cards and slices |
| powerbi-visuals-utils-formattingutils | 6.1.2 | `valueFormatter` |
| powerbi-visuals-utils-dataviewutils | 6.1.0 | `dataViewWildcard` (fx conditional formatting), Atlas Columns only |
| d3 | 7.9.0 | Atlas Flow imports only `d3-force` |
| Node.js | 22 (tested) | Docker image uses `node:22-bookworm` |

Const enums from the API typings (`powerbi.visuals.ValidatorType`, `powerbi.DrillType`, `VisualEnumerationInstanceKinds`) are inlined by the pbiviz TypeScript build. The bundle contains `type:0`, for example.

## Drill-down

- Capability: `"drilldown": {"roles": ["category"]}`. The drill role must be a **Grouping** role, and its condition must be **`max: 1`**. After that, users can drag several fields into the role (a hierarchy). Source: [Drill-down support](https://learn.microsoft.com/en-us/power-bi/developer/visuals/drill-down-support).
- The current level arrives as the category column. **Expand all down one level** sends several category columns (one per level). Build selection ids with `withCategory(column, row)` for every category column.
- The host handles drill mode, the header icons and the context-menu entries ("Drill down", "Drill up"). The visual needs to pass the point's selection id to `selectionManager.select` and `showContextMenu`.
- **Drilldown API** (API 4.7.0 and later): `host.drill({ roleName, drillType })`. The visual can show the next level, expand to the next level, or drill up on its own. Source: [Drilldown API](https://learn.microsoft.com/en-us/power-bi/developer/visuals/drilldown-api).
- `DrillType` (from the typings): `Up = 1`, `Down = 2` ("grouping becomes the union of the current grouping and the next level", i.e. expand all down one level), `MoveToNextlevel = 3` ("grouping becomes the next level exclusively", i.e. go to the next level).
- Which drill types are available right now: `dataViews[0].metadata.dataRoles.drillableRoles[roleName]` (an array of DrillType). `metadata.dataRoles.isDrillDisabled` tells you when drilling is off.
- Dynamic control: `"canDisableDrill": {"disabledByDefault": false}` in the drilldown capability, plus `host.setCanDrill(bool)`. See [Dynamic drill-down control](https://learn.microsoft.com/en-us/power-bi/developer/visuals/dynamic-drill-down).

## Format pane (formatting model)

- Cards: `formattingSettings.SimpleCard` with `slices`; `topLevelSlice` gives the on/off toggle in the card header; `visible = false` hides a slice or card. Build the pane in `getFormattingModel()` with `FormattingSettingsService.buildFormattingModel(model)`.
- Slices used: `ItemDropdown` (enumerations), `ColorPicker`, `NumUpDown` (options `minValue`/`maxValue` with `ValidatorType.Min/Max`), `Slider`, `ToggleSwitch`, `TextArea`, `TextInput` (placeholder "Auto"), `AutoDropdown` (display units: 0 = Auto, 1 = None, 1000, 1e6...).
- Per-item settings (series, node and category colors): one slice per item with `selector` set to the item's selector. Measures use `{ metadata: column.source.queryName }`; legend groups use `withSeries(values, group).getSelector()`; categories use the category selection id's selector.
- **Conditional formatting (fx)**: a ColorPicker with `selector: dataViewWildcard.createDataViewWildcardSelector(DataViewWildcardMatchingOption.InstancesAndTotals)`, `altConstantSelector: <the item's own selector>` and `instanceKind: powerbi.VisualEnumerationInstanceKinds.ConstantOrRule`. The rule results arrive per category in `dataView.categorical.categories[k].objects[i]`. This is how Atlas Columns does it, following Microsoft's conditional-formatting article; the rule results haven't been seen in real Power BI yet, so verify.
- **Analytics pane**: give the card `analyticsPane = true` and the capabilities object `"objectCategory": 2`.
- **Sorting**: `"sorting": {"default": {}}` turns on the visual's "Sort axis" menu. The data arrives already sorted.
- **Data reduction**: Columns `top 5000` categories and `top 60` series groups; Flow `top 30000` rows. Use `displayWarningIcon(title, text)` when the limit is hit.

## Host APIs used

`createSelectionIdBuilder` (`withCategory`, `withSeries`, `withMeasure`), `createSelectionManager` (`select`, `clear`, `showContextMenu`, `registerOnSelectCallback`, `getSelectionIds`), `tooltipService` (`show`/`move`/`hide`; coordinates relative to the visual), `colorPalette` (`getColor`, `foreground`, `background`, `isHighContrast`), `eventService` (`renderingStarted`, `renderingFinished`, `renderingFailed`), `hostCapabilities.allowInteractions`, `displayWarningIcon`, `createLocalizationManager` (strings in `stringResources/<locale>/resources.resjson`; pbiviz packages them automatically), `locale`, `drill`, `setCanDrill`.

High contrast: `colorPalette.isHighContrast`. Use `foreground` for marks and text and `background` for fills (Columns: hollow bars, with a different dash pattern per series).

## Report themes

- Schema: Microsoft's `reportThemeSchema-2.159.json` from [microsoft/powerbi-desktop-samples](https://github.com/microsoft/powerbi-desktop-samples/tree/main/Report%20Theme%20JSON%20Schema) (MIT, copy in `tools/schema/`).
- Top-level keys used: `name`, `dataColors`, `foreground`, `background`, `tableAccent`, `good`, `neutral`, `bad`, `maximum`, `center`, `minimum`, `null`, `firstLevelElements`…`fourthLevelElements`, `secondaryBackground`, `textClasses` (`title`, `header`, `label`, `callout`, each `{fontSize, color}`), `visualStyles`, `$schema`.
- Container cards for every visual (`visualStyles["*"]["*"]`):
  - `background {show, color, transparency}`
  - `border {show, color, radius, width}`
  - `dropShadow {show, position "Outer"|"Inner", preset "Bottom"|"BottomRight"|… |"Custom", color, transparency, shadowBlur, shadowDistance, shadowSpread, angle}`
  - `title {show, fontColor, fontSize, bold, …}`
  - `padding {top, bottom, left, right}`
  - `valueAxis {gridlineStyle "solid"|"dashed"|"dotted", gridlineColor}`
  - Colors use the `{"solid": {"color": "#hex"}}` format.
- The page background: `visualStyles.page["*"].background [{color, transparency}]`.
- **Custom visuals in themes**: `visualStyles` can target a custom visual by its GUID name (a Microsoft support engineer's answer on the [Fabric community forum](https://community.fabric.microsoft.com/t5/Custom-Visuals-Development/json-and-custom-visuals-with-power-bi-theme-possible/m-p/2702776/highlight/true)). The themes set `chart.look` and `palette.source` for both Atlas visuals. Not yet confirmed in this project's own testing.
- Built-in column and bar charts have no corner radius or gradient settings in the theme schema (their `dataPoint` card only has fill and border properties). That's why gradient, 3D and rounded bars need the custom visual.

## Importing and governance

- Import: in the Visualizations pane, select **…** › **Import a visual from a file**, pick the `.pbiviz`, confirm. To keep it, right-click the icon › **Pin to visualization pane**. Source: [Import a visual](https://learn.microsoft.com/power-bi/developer/visuals/import-visual).
- Microsoft's import guide says to enable developer mode in Power BI Desktop first: **File › Options and settings › Options › Current file › Report settings › Develop a visual** (only for the current session). Source: [Environment setup](https://learn.microsoft.com/en-us/power-bi/developer/visuals/environment-setup).
- Tenant setting **Allow visuals created using the Power BI SDK** (admin portal › Tenant settings › Power BI visuals). Microsoft documents it as disabled by default; it doesn't affect visuals in the organizational store. The Desktop group policy is `EnableCustomVisuals`. Source: [Manage Power BI visuals admin settings](https://learn.microsoft.com/power-bi/admin/organizational-visuals).
- Certified visuals get more features. Microsoft's examples are export to PowerPoint and showing in emails from report subscriptions. Uncertified visuals (these, today) don't get them. Source: [Certified Power BI visuals](https://learn.microsoft.com/en-us/power-bi/developer/visuals/power-bi-custom-visuals-certified). Certification needs, among other things, the source in a public repository, a clean lint, and no external requests.

## pbiviz packager suggestions not yet done

`pbiviz package --verbose` lists optional features. Done: Analytics pane (Columns), conditional formatting (Columns), warning icon. Not done (not needed so far): Fetch More Data, File Download, Launch URL, Local Storage, Modal Dialog.
