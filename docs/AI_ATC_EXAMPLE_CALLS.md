# AI ATC — example voice calls (optional, mission-specific)

> **Optional reference. This applies only to missions that bundle the community MOOSE
> "AI ATC" script** (an in‑`.miz` Lua ATC, e.g. `AI_ATC_v2.9.25.lua`). It is **not** a
> VAIVOX feature, not required to run VAIVOX, and **not shipped as runtime vocabulary**.
> Most missions do **not** include this script — if yours doesn't, ignore this file and
> use normal DCS ATC / VAICOM phraseology.

## What this is

Some DCS missions embed a custom MOOSE-based ATC that replaces the stock DCS controllers
with scripted Clearance / Ground / Tower / Departure / Approach / Range positions. You
interact with it through the **F10 radio menu**; with voice, VAICOM/VoiceAttack (the layer
VAIVOX sits behind) maps a spoken phrase onto the matching menu item.

The phraseology below was extracted from one such mission for illustration —
`AI_ATC_Nellis_v2.09.miz`, script **AI ATC v2.9.25**. Other missions that ship the same
script use the same call structure but may differ in frequencies, departure routes, and
field names. **Always confirm against the mission you are flying** (the in‑game helper
below prints the exact phrase for that mission).

## In-game helper: "Voice command assist"

The script can print the exact phrase to say at each step. Enable it from the radio menu:

```
F10 → AI_ATC → Clearance → Options... → Voice command assist
```

When on, an on-screen prompt shows the call expected for your current phase. The examples
in this file are that helper's built-in `VA_Instruction` table.

## Frequencies (example mission — tune the agency first)

| Agency                    | UHF     | VHF    |
| ------------------------- | ------- | ------ |
| ATIS                      | 270.1   | 240.1  |
| Clearance                 | 289.4   | 120.9  |
| Ground                    | 275.8   | 121.8  |
| Tower                     | 327.0   | 132.55 |
| Departure                 | 385.4   | 135.1  |
| Approach                  | 273.55  | 124.95 |
| BlackJack (Range Control) | 377.8   | 125.30 |
| NATCF Sally               | 317.525 | 126.65 |
| NATCF Lee                 | 254.4   | 119.35 |

## Example calls, in sortie order

Replace `<CALLSIGN>` with your flight callsign (selectable defaults include **Aspen**, Mig,
Viper, Hornet…; helos Pedro/Razor) and `<SQUAWK>` with the code Clearance assigns. Worked
example uses **Aspen 1‑1**.

**1. Clearance** (289.4)
- `Clearance delivery <CALLSIGN>, clearance on request, VFR, FLEX NORTH`
  — *"Clearance delivery Aspen one one, clearance on request, VFR, FLEX NORTH"*
- Readback: `<CALLSIGN>, squawk <SQUAWK>` — *"Aspen one one, squawk 3001"*

**2. Ground** (275.8)
- `Ground <CALLSIGN> request engine start`
- `Ground <CALLSIGN> request taxi to runway`
- `Ground <CALLSIGN> request taxi to parking` *(after landing)*

**3. Tower** (327.0)
- `Tower <CALLSIGN> holding short`
- `Tower <CALLSIGN> ready for takeoff`
- `Tower <CALLSIGN> request straight in` *(returning)*
- `Tower <CALLSIGN> 5 miles, gear down`

**4. Departure** (385.4)
- `Departure <CALLSIGN> airborne passing 3000`

**5. Approach** (273.55) — RTB
- `Approach <CALLSIGN> request RTB JAYSN approach`

**6. BlackJack / Range Control** (377.8)
- `BLACKJACK <CALLSIGN> with you, request Gate 3`
- `BLACKJACK <CALLSIGN> checking out, VFR, Gate 1`

**NATCF Sally / Lee** (RTB through working areas)
- `Sally <CALLSIGN> RTB, VFR, Gate 3`
- `LEE <CALLSIGN> RTB, VFR, Gate 1`

## Variables you can swap

- **Departure route** (in the clearance call): VFR → `FLEX NORTH` / `FLEX WEST` /
  `FLEX MMM TRANSITION`; IFR → `DREAM 7` / `FYTTR 7` / `MORMON MESA 8`. Helos → `GASS PEAK`,
  `DRY LAKE`, `RED HORSE`, `SUNRISE`, `SAR IFR`.
- **Squawk** readback options offered by the menu: `1001`–`7001`; your assigned code is a
  random `X001` per spawn.
- **Gate N** = the range entry/exit gate for BlackJack / range work.

## Known quirks (this example mission's script)

- **Approach assist prompt does not display.** The helper table keys the Approach entry as
  `Checkin` while the code requests state `CheckIn` (case mismatch), so no on-screen hint
  appears. The intended spoken call is still `Approach <CALLSIGN> request RTB JAYSN
  approach`.
- Tower `Base` and Departure `Flash` states are requested by the script but have **no**
  canned phrase, so the helper shows nothing for them.

## Relationship to VAIVOX

These phrases are a useful real-world phraseology source: they are good candidates for
focused **eval fixtures** under `tests/eval/` when validating reconciliation/phrase-snap
against ATC-style utterances. They are **documentation only** — VAIVOX does not bundle
mission-derived phrases as default vocabulary (consistent with
[ADR-0005](adr/0005-no-redistribution-of-vaicom-derived-data.md)); operators generate
their own vocabulary locally.
