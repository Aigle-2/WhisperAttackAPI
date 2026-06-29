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
- `Ground <CALLSIGN> request taxi to runway` / `request taxi for takeoff`
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

## VAIVOX resolution behavior

VAIVOX accepts the full call; it does not require speaking only the final menu label. It
loads the user's local VAICOM `Export/keywords.html` and joins each exact `Action ...`
identifier to its spoken aliases, with a small set of conservative AI_ATC aliases for common
labels such as `Request Taxi to Runway` (`request taxi for takeoff`). It then matches an
exact, contiguous multi-token label or trusted alias inside the reconciled phrase, so a call
ending in `IFR DREAM 7` selects `DREAM 7` even when the live menu also contains numeric
entries such as `1`, `6`, and `7`. A single-token menu item is intentionally selectable only
as the complete spoken command, preventing incidental callsign digits from dispatching it.
The explicit forms `Set call sign <CALLSIGN>` and `Set callsign <CALLSIGN>` (including the
common STT inflection `Sets callsign`) are the safe
exception: they select a unique exact live label, so `Set call sign Chaos` fires `Chaos`,
while `Set callsign digit six` fires the numeric leaf under the callsign path. AI_ATC's
`Set Integer` menu exposes only one digit leaf per flight number; if an operator says a
full DCS callsign number such as `Set call sign 13`, VAIVOX fires the `1` leaf. A combined
phrase such as `Set callsign Chaos 61` is recognized but deliberately rejected without UDP
or VoiceAttack fallback: this mission exposes no safe atomic combined action, and its two
separate callbacks can overwrite the requested prefix.

Only the settled, path-aware live DCS menu is executable. Log-only entries remain visible as
unavailable diagnostics; an inactive or ambiguous action is rejected rather than routed to
a similarly named VoiceAttack command.

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
