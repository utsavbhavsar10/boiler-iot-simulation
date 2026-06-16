"""
knowledge_base/boiler_guides.py

All 12 knowledge base documents for the boiler and chimney system.
These are indexed into ChromaDB and retrieved by the agent at query time.

HOW TO ADD A NEW DOCUMENT:
1. Add a new dict to KNOWLEDGE_DOCUMENTS following the same format
2. Give it a unique "id" (lowercase, underscores, no spaces)
3. Give it a descriptive "title"
4. Write the "content" as plain text (no markdown, no JSON)
5. Run: python knowledge_base/indexer.py --mode=add --id=your_new_id
   (or full re-index: python knowledge_base/indexer.py --mode=full)

HOW TO UPDATE AN EXISTING DOCUMENT:
1. Find the document by its "id" in this list
2. Edit the "content" text
3. Run: python knowledge_base/indexer.py --mode=update --id=the_document_id

HOW TO REMOVE A DOCUMENT:
1. Delete the dict from KNOWLEDGE_DOCUMENTS
2. Run: python knowledge_base/indexer.py --mode=full
   (full re-index is safest for deletions)
"""
KNOWLEDGE_DOCUMENTS = [

    # ══════════════════════════════════════════════════════════════
    # CATEGORY 1A — BOILER FAULT GUIDES
    # ══════════════════════════════════════════════════════════════

    {
        "id": "fault_high_pressure",
        "category": "boiler_fault",
        "title": "HIGH_PRESSURE Fault — Complete Guide",
        "content": """
HIGH_PRESSURE fault code is triggered when boiler steam pressure exceeds 14 bar.
This is a CRITICAL severity fault. Immediate action is required.
Normal operating range for boiler pressure is 10 to 14 bar.

WHAT IS HAPPENING:
The boiler is generating steam pressure faster than it is being consumed or released.
Pressure will continue rising until the cause is removed or the pressure relief valve opens.
Above 16 bar, mechanical failure risk increases significantly.
Above 18 bar, explosion risk becomes serious.

ROOT CAUSES (in order of likelihood):
Cause 1: Pressure relief valve stuck closed or set too high.
  The relief valve is the safety device that should automatically
  open when pressure exceeds the setpoint (usually 14.5 to 15 bar).
  If it is stuck, pressure keeps rising with no automatic safety release.
Cause 2: Downstream steam outlet valve closed or partially closed.
  If the valve that lets steam leave the boiler is closed, the steam
  has nowhere to go. Pressure builds inside the vessel.
Cause 3: Burner firing rate too high for current steam demand.
  If steam demand has dropped (e.g. a downstream process stopped)
  but the burner is still firing at the same rate, the boiler makes
  more steam than is being used. Pressure rises.
Cause 4: Scale buildup on heat exchanger surfaces.
  Mineral scale insulates the heating surfaces. More heat stays in
  the combustion chamber instead of transferring to water.
  This causes localised overheating which drives up pressure.
Cause 5: Boiler overfed with water, water level too high.
  Excess water reduces the steam space, reducing volume for pressure
  equalisation and causing rapid pressure rise.

STEP BY STEP IMMEDIATE ACTIONS:
Step 1: Reduce burner to minimum firing rate immediately.
  Do not shut off completely yet unless pressure exceeds 16 bar.
  Gradual reduction prevents thermal shock.
Step 2: Check downstream steam outlet valve is fully open.
  Walk to the main steam header and verify isolation valves are open.
Step 3: Manually test the pressure relief valve.
  Lift the test lever briefly. Steam should escape freely.
  If no steam comes out, the valve is stuck. This is an emergency.
Step 4: If pressure reaches 16 bar, shut off burner completely.
Step 5: If pressure reaches 18 bar, evacuate the boiler room.
  This is a potential explosion risk situation.
Step 6: Do not restart until root cause is identified and fixed.
Step 7: Call a certified boiler engineer for inspection before restart.

PREVENTION MEASURES:
Test pressure relief valve monthly using the lift test lever.
Install a pressure trend alert at 12 bar to warn before reaching 14 bar.
Schedule annual boiler inspection including relief valve calibration.
Monitor downstream steam demand and adjust burner firing rate accordingly.
Perform annual chemical descaling to prevent scale-related pressure issues.

IMPORTANT SAFETY NOTE:
Never operate a boiler above 15 bar without engineering authorisation.
The Indian Boiler Regulations (IBR) require that all pressure-containing
components are rated and certified for the maximum allowable working pressure.
        """
    },
 {
        "id": "fault_low_water_level",
        "category": "boiler_fault",
        "title": "LOW_WATER_LEVEL Fault — Complete Guide",
        "content": """
LOW_WATER_LEVEL fault code is triggered when boiler drum water level
drops below 40 percent. This is a CRITICAL severity fault.
Normal drum water level range is 40 to 60 percent.

THIS IS THE MOST DANGEROUS BOILER CONDITION.
A boiler with insufficient water will overheat its tubes.
Overheated tubes warp, crack, and can rupture violently.
A tube rupture releases high-pressure steam explosively.
Most industrial boiler explosions in history trace to low water.

WHAT IS HAPPENING:
Water is leaving the boiler faster than it is being replaced.
The exposed heating surfaces (tubes, furnace walls) are receiving
heat from combustion but have no water to absorb it.
Metal temperature rises rapidly. Above 450 degrees Celsius,
carbon steel tubes lose structural integrity.

ROOT CAUSES (in order of likelihood):
Cause 1: Feed water pump failure.
  The pump that continuously supplies water to the boiler has
  failed electrically (tripped breaker, burnt motor) or mechanically
  (worn impeller, cavitation, seized shaft).
  Feed water flow rate drops to zero. Level falls rapidly.
Cause 2: Feed water control valve stuck closed.
  The automatic valve controlling water supply has failed closed.
  Pump is running but water cannot pass through.
Cause 3: Steam demand suddenly increased beyond feed capacity.
  A large steam consumer came online unexpectedly.
  Water is converted to steam faster than the pump can replace it.
Cause 4: Boiler tube or fitting leak.
  Water is escaping through a crack or failed fitting.
  Look for unexpected steam clouds or water on the boiler room floor.
Cause 5: Water level gauge or sensor failure.
  The level reading may be incorrect.
  The actual water level could be normal.
  Always visually verify before acting on a sensor reading.

STEP BY STEP IMMEDIATE ACTIONS:
Step 1: SHUT OFF BURNER IMMEDIATELY. No exceptions.
  This is mandatory. You cannot run a low-water boiler.
Step 2: Do NOT add cold water to a hot boiler.
  If the boiler has been running hot without water for even
  a few minutes, the tubes are extremely hot. Cold water on
  hot dry tubes causes thermal shock and tube cracking.
  This is called a cold water incident and causes more damage
  than the original low water condition.
Step 3: Verify the level reading with physical inspection.
  Look at the sight glass directly. Is the reading accurate?
Step 4: Check feed water pump operation.
  Is it running? Check the electrical panel for a tripped breaker.
  Is suction valve open? Is discharge valve open?
Step 5: Check feed water control valve position.
  Is it open? Try manual override if available.
Step 6: Inspect visible boiler surfaces for steam or water leaks.
  Look for unusual moisture, steam clouds, or water on the floor.
Step 7: Let boiler cool to below 60 degrees Celsius before
  restoring water if the pump was off for more than 10 minutes.
Step 8: Call a certified boiler engineer before restarting.
  A qualified engineer must inspect for tube damage before the
  boiler is returned to service.

PREVENTION MEASURES:
Inspect feed water pump weekly. Check impeller wear quarterly.
Test low water cutoff device monthly using the slow drain test.
Install duplicate water level sensors for redundancy.
Install automatic feed water control with low-level alarm at 45 percent.
Check drum level manually every 4 hours during operation.
Maintain a boiler log with level readings at each shift change.
        """
    },
    
    {
        "id": "fault_high_temperature",
        "category": "boiler_fault",
        "title": "HIGH_TEMPERATURE Fault — Complete Guide",
        "content": """
HIGH_TEMPERATURE fault code is triggered when boiler water or steam
temperature exceeds the normal maximum of 100 degrees Celsius above
the design specification. This is a WARNING severity fault.
Normal boiler water temperature range is 60 to 100 degrees Celsius.

WHAT IS HAPPENING:
The boiler water is absorbing more heat than it should at current
operating conditions. This may indicate a heat transfer problem,
an over-firing condition, or a water circulation issue.
If left uncorrected it can progress to a CRITICAL condition.

ROOT CAUSES:
Cause 1: Scale or sludge deposits on heating tube surfaces.
  Mineral scale is a poor conductor of heat.
  A scale layer of just 1 millimetre on the tube inner surface
  reduces heat transfer efficiency by approximately 10 percent.
  The water does not absorb heat efficiently, so temperature rises.
  This is the most common long-term cause of high temperature.
Cause 2: Burner over-firing.
  Burner is delivering more heat than the boiler design allows.
  Check burner settings and fuel pressure.
Cause 3: Low water circulation rate.
  In a circulation boiler, a pump moves water through the heating
  tubes. If this pump slows or fails, water stays in the hot zone
  longer than designed and picks up more heat.
Cause 4: Incorrect fuel-to-air ratio running rich.
  Too much fuel relative to air produces a hotter flame.
  The combustion temperature is higher, pushing more heat into
  the water.
Cause 5: Blocked flue gases inside boiler passages.
  If soot or debris blocks the internal gas passages, combustion
  products spend more time inside the boiler transferring heat.

RELATIONSHIP WITH FLUE TEMPERATURE:
If boiler water temperature is high AND chimney flue temperature
is also high simultaneously, scale buildup is almost certainly the cause.
Heat cannot pass through scale to the water, so both the combustion
side (high flue temp) and the water side (high water temp) run hot.
This dual-high pattern is the classic scale signature.

CONTROL ACTIONS:
Reduce burner firing rate by 20 percent increments.
Check water circulation pump speed and operation if fitted.
Measure flue gas CO2 percentage. If above 14 percent,
  mixture is too rich. Open combustion air damper.
If scale buildup is suspected: schedule chemical descaling treatment.
  Do not delay. Scale buildup worsens over time and will
  eventually cause HIGH_PRESSURE and efficiency loss as well.

PREVENTION MEASURES:
Annual chemical descaling treatment.
Monthly water quality testing. Hardness should be below 50 ppm.
Quarterly combustion analysis to verify correct fuel-air ratio.
Trend monitoring of flue temperature.
  A flue temperature rising by 5 degrees per week indicates
  active scale formation. Schedule descaling before it worsens.
        """
    },

    {
        "id": "fault_low_fuel_flow",
        "category": "boiler_fault",
        "title": "LOW_FUEL_FLOW Fault — Complete Guide",
        "content": """
LOW_FUEL_FLOW fault code is triggered when fuel flow rate drops
below 5 litres per minute. Normal range is 5 to 20 litres per minute.
This is a WARNING severity fault.

WHAT IS HAPPENING:
The burner is receiving less fuel than required for the current
heat demand. Steam production will drop. If severe enough, the
burner may extinguish. Pressure and temperature will fall.

ROOT CAUSES:
Cause 1: Fuel supply pressure drop.
  The fuel supply line pressure has dropped. Could be supply
  network pressure reduction, or a valve partially closing.
Cause 2: Fuel filter blocked or heavily fouled.
  Fuel filters collect debris from the supply line.
  A blocked filter restricts fuel flow to the burner.
Cause 3: Fuel control valve stuck or failing.
  The valve that regulates fuel delivery to the burner
  has stuck in a partially closed position.
Cause 4: Burner nozzle partially blocked.
  The nozzle that atomises fuel has carbon deposits
  narrowing the orifice, restricting flow.
Cause 5: Fuel pump wear or failure.
  The pump delivering fuel from the storage tank
  to the burner has reduced output due to wear.

CONTROL ACTIONS:
Check fuel supply line pressure at the meter or supply connection.
Inspect and clean or replace the fuel filter.
Verify fuel control valve is in the fully open position.
Inspect burner nozzle for carbon deposits. Clean with solvent.
Check fuel pump delivery pressure against specification.

PREVENTION:
Replace fuel filter every 3 months or after heavy use periods.
Annual burner service including nozzle inspection and cleaning.
Install fuel pressure gauge with low-pressure alarm.
        """
    },

    {
        "id": "fault_abnormal_airflow",
        "category": "boiler_fault",
        "title": "ABNORMAL_AIRFLOW Fault — Complete Guide",
        "content": """
ABNORMAL_AIRFLOW fault code is triggered when combustion air flow
falls below 100 cubic metres per hour or exceeds 300 cubic metres
per hour. Normal range is 100 to 300 cubic metres per hour.

TOO LOW (below 100 cubic metres per hour):
Insufficient combustion air reaching the burner.
Result: incomplete combustion, high CO, high CO2, black smoke,
  inefficient operation, potential burner instability.
Causes: blocked combustion air filter, air damper stuck closed,
  blocked air intake duct, burner fan failure or low speed.

TOO HIGH (above 300 cubic metres per hour):
Excess air diluting combustion gases unnecessarily.
Result: flame cooling, reduced efficiency, high fuel consumption,
  excessive heat loss through chimney, low CO2 in flue gas.
Causes: air damper stuck open, combustion analysis not performed,
  leaking boiler casing allowing cold air infiltration.

COMBUSTION AIR RELATIONSHIP WITH FLUE GAS:
Correct air supply produces: CO2 10-13 percent, O2 3-6 percent, CO below 30 ppm.
Low air produces: CO2 above 14 percent, O2 below 3 percent, CO above 50 ppm.
Excess air produces: CO2 below 8 percent, O2 above 8 percent, CO near zero.

CONTROL ACTIONS:
Measure current O2 and CO2 percentages in flue gas.
Adjust combustion air damper in small increments.
After each adjustment, wait 2 minutes for readings to stabilise.
Target O2 of 4 to 6 percent with CO2 of 10 to 12 percent.
Check air filter and replace if blocked.
Verify fan motor speed is correct.

PREVENTION:
Replace combustion air filter every 3 months.
Annual combustion analysis and burner tuning by certified engineer.
Quarterly flue gas spot checks using portable analyser.
        """
    },

    # ══════════════════════════════════════════════════════════════
    # CATEGORY 1B — CHIMNEY FAULT GUIDES
    # ══════════════════════════════════════════════════════════════

    {
        "id": "fault_high_co",
        "category": "chimney_fault",
        "title": "HIGH_CO Fault — Complete Guide",
        "content": """
HIGH_CO fault code is triggered when carbon monoxide concentration
in chimney flue gas exceeds 50 ppm (parts per million).
This is a CRITICAL severity fault. Personnel safety risk.
Normal CO range in flue gas is 0 to 50 ppm.

WHAT CARBON MONOXIDE IS:
Carbon monoxide (CO) is produced when fuel does not burn completely.
In complete combustion: fuel + enough air = CO2 + water vapour.
In incomplete combustion: fuel + insufficient air = CO + water vapour.
CO is colourless and has no smell. You cannot detect it without instruments.
CO is poisonous. It binds to haemoglobin in blood, preventing oxygen transport.

PERSONNEL SAFETY THRESHOLDS (mandatory knowledge):
0 to 50 ppm: Normal operation range. No health risk.
50 to 200 ppm: WARNING. Investigate and increase ventilation immediately.
  At 200 ppm: symptoms appear after 2 to 3 hours (headache, dizziness).
200 to 400 ppm: Evacuate boiler room. Life-threatening within 3 hours.
Above 800 ppm: Life-threatening within 45 minutes. Emergency evacuation.
Above 1600 ppm: Fatal within 1 hour.

INSTALL A CO DETECTOR ALARM IN EVERY BOILER ROOM.
This is a legal requirement under Indian factory safety regulations.

ROOT CAUSES:
Cause 1: Insufficient combustion air supply.
  Not enough oxygen reaching the burner for complete combustion.
  This is the most common cause.
  Check: O2 below 3 percent and CO2 above 14 percent together
  confirm this diagnosis.
Cause 2: Burner nozzle fouling with carbon deposits.
  The nozzle cannot atomise fuel correctly.
  Fuel droplets are too large to burn completely.
  Check: CO is high but O2 is normal (enough air, but poor mixing).
Cause 3: Cracked heat exchanger or furnace wall.
  Combustion gases are bypassing the normal flow path.
  They may be mixing with room air instead of going up the chimney.
  Check: CO in boiler room air, not just in the flue gas.
Cause 4: Blocked combustion air intake filter.
  Filter is clogged with dust. Air supply is restricted.
  Check: Air flow rate is low, filter is visibly dirty.
Cause 5: Fuel pressure too low causing poor atomisation.
  Insufficient fuel pressure means the nozzle cannot break
  fuel into fine enough droplets for complete combustion.

STEP BY STEP CONTROL ACTIONS:
Step 1: If CO exceeds 200 ppm — ventilate the boiler room immediately.
  Open all doors and windows. Turn on ventilation fans.
Step 2: Open combustion air damper by 10 percent increments.
Step 3: Measure O2 in flue gas after each damper adjustment.
  O2 should rise as you add more air. Target: 4 to 6 percent O2.
Step 4: If O2 rises but CO stays high, burner nozzle fouling is likely.
  Shut down burner and inspect nozzle. Clean or replace.
Step 5: Check and replace combustion air filter if blocked.
Step 6: If CO exceeds 400 ppm — shut down boiler immediately.
  Evacuate all personnel from boiler room.
Step 7: Inspect heat exchanger for cracks before restarting.

PREVENTION:
Install CO detector with alarm in boiler room. Test monthly.
Annual burner service including nozzle cleaning and replacement.
Replace combustion air filter every 3 months.
Quarterly flue gas CO measurement using portable analyser.
Maintain boiler room ventilation. Minimum 10 air changes per hour.
        """
    },

    {
        "id": "fault_blocked_flue",
        "category": "chimney_fault",
        "title": "BLOCKED_FLUE Fault — Complete Guide",
        "content": """
BLOCKED_FLUE fault code is triggered when chimney draft pressure
becomes less negative than minus 2 Pascals.
Normal draft pressure range is minus 2 to minus 5 Pascals.
This is a CRITICAL severity fault.

UNDERSTANDING DRAFT PRESSURE:
Draft is the negative pressure (suction) inside the chimney.
It is created by the difference in density between hot flue gas
inside the chimney and cooler air outside.
Hot gases are less dense than cool air. They rise. This rising
creates suction at the bottom, pulling combustion air through
the burner and drawing flue gases up and out.
Draft is always expressed as a negative number during operation.
More negative means stronger suction. Less negative means weaker.
Zero means no draft. Positive means reverse flow (back pressure).

WHAT IS HAPPENING:
The chimney cannot pull flue gases upward effectively.
Combustion gases may back-flow into the boiler room.
This creates CO accumulation risk in the boiler room.

ROOT CAUSES:
Cause 1: Soot and ash accumulation inside chimney flue.
  Over months of operation, combustion residues build up on
  the inner chimney wall. This narrows the effective diameter,
  increasing flow resistance and reducing draft.
  Annual chimney sweeping prevents this.
Cause 2: Physical obstruction at chimney outlet.
  Bird nests are extremely common in industrial chimneys.
  Debris, leaves, or dead birds can partially block the outlet.
  A visual inspection from ground level often reveals this.
Cause 3: Chimney liner collapse or structural damage.
  The internal liner of the chimney has fractured or shifted.
  Requires camera inspection to diagnose.
Cause 4: Downdraught from wind.
  Wind direction and speed can temporarily push air back down
  the chimney. This is especially common in urban areas with
  nearby tall buildings creating complex wind patterns.
  A chimney cowl prevents most downdraught conditions.
Cause 5: Building negative pressure.
  The building HVAC system is extracting more air from the
  building than it is supplying. This creates negative pressure
  inside the building, which can reverse chimney flow.
  Seen in tightly sealed modern buildings.

CONTROL ACTIONS:
Shut down boiler. Do not operate with a blocked flue.
The risk of CO accumulation in the boiler room is too high.
With boiler off, visually inspect chimney outlet from ground level.
Look for obvious obstructions (nests, debris, cowl damage).
Use a draft gauge at multiple heights to locate blockage zone.
Schedule professional chimney sweep for soot removal.
For suspected structural collapse: arrange camera CCTV inspection
  before scheduling a sweep (sweeping a collapsed liner
  can displace debris and worsen the blockage).

PREVENTION:
Annual chimney sweep by qualified sweep contractor.
Install a chimney cowl (terminal) to prevent bird nesting
  and reduce downdraught.
Monthly draft pressure monitoring. Trend below minus 2 Pa
  for more than 3 consecutive readings = schedule inspection soon.
Inspect chimney exterior and outlet after severe storms.
        """
    },

    {
        "id": "fault_high_flue_temp",
        "category": "chimney_fault",
        "title": "HIGH_FLUE_TEMPERATURE Fault — Complete Guide",
        "content": """
HIGH_FLUE_TEMPERATURE fault code is triggered when chimney outlet
temperature exceeds 250 degrees Celsius.
Normal flue temperature range is 150 to 250 degrees Celsius.
This is a WARNING severity fault.

WHAT IS HAPPENING:
Combustion gases are exiting the chimney hotter than they should.
This means the boiler heat exchanger is not transferring as much
heat from the flue gases to the water as it is designed to.
Hot flue gases represent wasted energy leaving through the chimney.

EFFICIENCY IMPACT (critical for client cost awareness):
Every 10 degrees Celsius above optimal flue temperature equals
approximately 1 percent reduction in boiler thermal efficiency.
Example: Optimal flue temperature is 200 degrees Celsius.
  Measured flue temperature is 260 degrees Celsius.
  Difference is 60 degrees Celsius.
  Efficiency loss: approximately 6 percent.
  For a boiler consuming 50,000 litres of fuel per year:
  6 percent waste equals 3,000 litres of fuel wasted annually.
  At current fuel prices, this is a significant operating cost.
The client should understand this fault directly costs them money.

ROOT CAUSES:
Cause 1: Scale buildup on boiler heat exchanger tubes.
  This is by far the most common cause.
  Mineral deposits from hard water accumulate on tube surfaces.
  Scale is a thermal insulator. Heat cannot transfer through it.
  Flue gases stay hot because the water cannot absorb their heat.
  Signature: Flue temperature rises gradually over weeks or months.
Cause 2: Excessive excess air in combustion.
  Too much cold combustion air is passing through the boiler.
  This cool air dilutes the hot flue gases and passes straight
  through without useful heat transfer.
  O2 above 8 percent confirms excess air condition.
Cause 3: Missing or damaged flue gas baffles inside boiler.
  Baffles force flue gases to take a longer path through the heat
  exchanger, increasing contact time and heat transfer.
  If baffles are missing or broken, gases take a shortcut.
Cause 4: Boiler operating significantly above design capacity.
  Higher heat input than designed means gases move faster through
  the heat exchanger, reducing heat transfer time.
Cause 5: Short-cycling operation.
  Boiler starts, quickly reaches temperature, shuts off.
  During start-up, the heat exchanger is cold and absorbs heat
  rapidly. But during short on-periods, the exchanger never
  reaches steady-state efficient operation.

TREND ANALYSIS (how to detect scale buildup early):
Monitor flue temperature daily.
If flue temperature rises more than 10 degrees per week
with no change in burner settings or fuel type,
scale buildup is almost certainly occurring.
Schedule descaling within 2 to 4 weeks.
Do not wait for the fault threshold to be reached.
Early intervention costs less than emergency descaling.

CONTROL ACTIONS:
Check O2 percentage. If above 8 percent, reduce air supply.
  Close combustion air damper by 5 percent increments.
  Recheck O2 after each adjustment. Target 4 to 6 percent.
Inspect flue baffles during next planned maintenance outage.
  Replace any missing or cracked baffles.
Schedule chemical descaling if scale is suspected.
Review boiler load profile. Is it being asked to short-cycle?
  Consider installing a thermal buffer tank to smooth demand.

PREVENTION:
Monthly flue temperature recording and trend monitoring.
Annual heat exchanger inspection and tube cleaning.
Quarterly water hardness testing. Treat if above 50 ppm hardness.
Quarterly combustion analysis to verify correct air-fuel ratio.
        """
    },
  # ══════════════════════════════════════════════════════════════
    # CATEGORY 2 — MULTI-SENSOR DIAGNOSTIC GUIDES
    # ══════════════════════════════════════════════════════════════

    {
        "id": "diag_pressure_plus_low_water",
        "category": "multi_sensor_diagnostic",
        "title": "Combined Diagnosis: HIGH_PRESSURE + LOW_WATER_LEVEL Simultaneously",
        "content": """
When HIGH_PRESSURE fault and LOW_WATER_LEVEL fault occur at the same time,
this is a DOUBLE CRITICAL emergency situation requiring immediate boiler shutdown.

DO NOT TRY TO FIX ONE FAULT WHILE THE OTHER PERSISTS.
The combination is more dangerous than either fault alone.

WHAT IS HAPPENING:
The feed water system has failed while the burner continues to fire.
Water in the boiler is being converted to steam faster than it is
being replaced by feed water.
As water level drops, steam space increases, causing pressure to rise.
Simultaneously, exposed heating surfaces are overheating due to lack of water.
This is a mechanical and safety emergency.

MOST LIKELY ROOT CAUSE:
Feed water pump has failed mechanically or electrically.
The pump stopped delivering water. The burner continued firing.
Over several minutes, water level has dropped and pressure has risen.

ALTERNATIVE CAUSE:
A boiler tube has cracked or failed.
Water is escaping through the breach.
This is less common but more structurally serious.
Look for unexpected steam or water emerging from the boiler casing.

IMMEDIATE RESPONSE (follow in exact order):
Step 1: SHUT OFF BURNER IMMEDIATELY.
  This is the single most important action. Remove the heat source.
Step 2: DO NOT OPEN THE SAFETY RELIEF VALVE MANUALLY.
  Steam at high pressure escaping in a confined space is extremely
  dangerous to personnel. Let the pressure drop naturally.
Step 3: DO NOT ADD COLD WATER TO A HOT LOW-WATER BOILER.
  This causes thermal shock and can crack tubes.
  Wait until boiler cools to below 60 degrees Celsius.
Step 4: Isolate the boiler from the steam distribution system.
  Close the main steam outlet valve.
Step 5: DO NOT RESTART THE BOILER.
  This boiler must not be restarted until inspected by a certified
  boiler engineer. Tube damage may have occurred. Operating a boiler
  with damaged tubes can cause catastrophic failure.
Step 6: Contact a certified boiler inspector.
  Under Indian Boiler Regulations, a certified inspector must
  examine the boiler before it can legally return to service
  after a low water incident.

ROOT CAUSE INVESTIGATION AFTER SHUTDOWN:
Check feed water pump electrical supply. Check breaker in panel.
Check pump mechanical state. Attempt to turn shaft by hand.
Check suction and discharge valves. Are they open?
Check feed water control valve. Is it open or stuck?
Review monitoring history. How long was the pump off before alarm?
Inspect boiler exterior for leaks, cracks, or distorted surfaces.
        """
    },

    {
        "id": "diag_high_co2_low_o2",
        "category": "multi_sensor_diagnostic",
        "title": "Combined Diagnosis: HIGH_CO2 + LOW_O2 in Flue Gas",
        "content": """
When CO2 percentage in flue gas exceeds 14 percent AND oxygen percentage
is below 3 percent simultaneously, this confirms a rich combustion mixture.
Too much fuel relative to combustion air. Incomplete combustion is occurring.
CO will also be elevated in this situation.

UNDERSTANDING THE RELATIONSHIP:
CO2 and O2 in flue gas always move in opposite directions.
When air supply increases: O2 rises, CO2 falls, CO falls.
When air supply decreases: O2 falls, CO2 rises, CO rises.
CO2 above 14 percent with O2 below 3 percent is an unambiguous
signal that combustion air is insufficient for the fuel being burned.

WHY THIS MATTERS:
Incomplete combustion wastes fuel. Carbon that should become CO2
instead becomes CO, which goes up the chimney as unburned energy.
CO is toxic to personnel in the boiler room.
A rich mixture can also cause sooting of heat exchanger surfaces
and burner components, requiring more frequent maintenance.

DIAGNOSIS CERTAINTY:
CO2 high + O2 low together means insufficient air. This is definitive.
You do not need to check other causes when both readings confirm this.

STEP BY STEP CONTROL:
Step 1: Open combustion air damper by 10 percent.
  Make one adjustment at a time. Do not jump to large changes.
Step 2: Wait 2 to 3 minutes for readings to stabilise.
  Flue gas composition lags behind damper changes by 1 to 3 minutes.
Step 3: Measure O2 and CO2 again.
  O2 should have risen. CO2 should have fallen.
  CO should also be falling if air was the root cause.
Step 4: Continue adjusting damper in 5 percent increments
  until O2 reaches 4 to 6 percent and CO2 reaches 10 to 12 percent.
Step 5: If O2 rises but CO remains high after air correction:
  The problem is now burner nozzle fouling, not air supply.
  Shut down and inspect nozzle. Clean or replace as needed.
Step 6: Check combustion air filter condition.
  If filter is visibly dirty, replace it. A dirty filter causes
  gradual drift toward rich combustion over weeks.

TARGET FLUE GAS COMPOSITION:
O2: 4 to 6 percent (optimal for natural gas boilers)
CO2: 10 to 12 percent
CO: below 30 ppm
Flue temperature: 150 to 220 degrees Celsius

PREVENTION:
Quarterly flue gas analysis and burner adjustment.
Air filter replacement every 3 months.
Annual burner service by qualified engineer.
        """
    },

    # ══════════════════════════════════════════════════════════════
    # CATEGORY 3 — SENSOR INTERPRETATION GUIDES
    # ══════════════════════════════════════════════════════════════

    {
        "id": "guide_co2_interpretation",
        "category": "sensor_interpretation",
        "title": "How to Interpret CO2 Percentage in Chimney Flue Gas",
        "content": """
CO2 percentage in chimney flue gas is the primary indicator of
combustion efficiency for a boiler. Understanding what CO2 readings
mean allows early detection of combustion problems.

WHAT CO2 IN FLUE GAS REPRESENTS:
CO2 is the product of complete combustion of carbon in fuel.
Higher CO2 means more carbon has been fully burned per unit of air passing through.
Lower CO2 means either excess air is diluting the gases
or incomplete combustion is occurring.

READING INTERPRETATION GUIDE:
CO2 below 8 percent:
  Excessive combustion air. Too much cold air passing through.
  Fuel is being burned but most of the flue gas is diluted with
  excess air that served no combustion purpose.
  Result: Efficiency loss, high fuel consumption, unnecessarily
  high flue temperature.
  Action: Reduce air supply. Close combustion air damper.

CO2 between 8 and 12 percent:
  Good combustion. Adequate but not excessive air supply.
  Most boilers operate well in this range.
  No immediate action needed.

CO2 between 12 and 14 percent:
  Excellent combustion efficiency. Near-stoichiometric conditions.
  The boiler is burning fuel as efficiently as practical.
  This is the ideal target range for most natural gas boilers.
  No action needed.

CO2 above 14 percent:
  Insufficient combustion air. Rich mixture.
  Carbon cannot find enough oxygen for complete combustion.
  CO will also be elevated. Personnel safety risk.
  Action: Increase air supply immediately.

RELATIONSHIP WITH O2:
CO2 and O2 always move in opposite directions.
As you add more air: O2 rises, CO2 falls.
As you reduce air: O2 falls, CO2 rises.
Use both readings together for precise diagnosis.
If CO2 high AND O2 low: definitely insufficient air.
If CO2 low AND O2 high: definitely excessive air.

TREND ANALYSIS OVER TIME:
CO2 rising gradually over weeks without changing settings:
  Likely cause: combustion air filter becoming blocked.
  Less air entering means proportionally more CO2.
  Check and replace filter.

CO2 dropping gradually over weeks without changing settings:
  Likely cause: air leaking into flue gas path from casing cracks.
  Cool air dilutes flue gases. CO2 percentage drops.
  Inspect boiler casing and flue connections for gaps.

CO2 fluctuating widely and rapidly:
  Indicates combustion instability.
  Could be burner cycling, fuel pressure fluctuations,
  or air damper mechanical problem.
  Investigate burner control system.

SEASONAL VARIATION:
In very cold weather, incoming combustion air is denser.
More oxygen atoms per cubic metre of air.
The same air flow setting will produce slightly richer mixture.
CO2 may rise by 0.5 to 1 percent in winter. This is normal.
Adjust damper slightly in winter for precise tuning.
        """
    },

    {
        "id": "guide_draft_pressure",
        "category": "sensor_interpretation",
        "title": "How to Interpret Chimney Draft Pressure",
        "content": """
Draft pressure is the negative pressure (suction) measured inside
the chimney flue. It is the driving force that pulls combustion
air through the burner and expels flue gases safely upward.
Draft is always a negative value during normal boiler operation.

UNDERSTANDING NEGATIVE PRESSURE:
Negative pressure means the pressure inside the chimney is lower
than atmospheric pressure outside.
This lower pressure sucks air in at the burner end and pushes
flue gases up and out at the chimney top.
More negative = stronger suction = better draft.
Less negative = weaker suction = poorer draft.
Zero or positive = no draft or reverse flow = dangerous condition.

NORMAL OPERATING RANGE:
The normal draft pressure range is minus 2 to minus 5 Pascals.
This provides sufficient suction for combustion air flow
without excessive heat loss from over-drafting.

READING INTERPRETATION:
Draft between 0 and minus 2 Pascals (insufficient draft):
  The chimney cannot pull flue gases upward effectively.
  Possible causes: soot blockage, physical obstruction at top,
  structural damage to liner, downdraught from wind.
  Action: Shut down boiler. Inspect chimney before restarting.

Draft between minus 2 and minus 5 Pascals (normal):
  Good draft. Chimney is working correctly.
  No action needed.

Draft between minus 5 and minus 10 Pascals (excess draft):
  More suction than needed.
  Excess cold air is being pulled through the system,
  reducing efficiency and lowering combustion temperature.
  Possible causes: chimney too tall, flue gas temperature very high,
  strong wind conditions, air register too open.
  Action: Consider installing a draft diverter or adjusting air register.

Draft above 0 Pascals (positive, back pressure):
  Flue gases are flowing back into the boiler room. EVACUATE.
  This is an emergency condition.
  Combustion products including CO are entering the workspace.

RELATIONSHIP WITH FLUE TEMPERATURE:
Draft and flue temperature are closely related.
Hotter flue gases are less dense than cooler air outside.
This density difference creates the buoyancy force driving draft.
Higher flue temperature = stronger natural draft.
If flue temperature drops significantly, draft will also weaken.
In very hot summer weather, the temperature difference between
flue gas and outside air is smaller, so draft may be 0.5 Pa weaker.
This is normal seasonal variation.

SEASONAL AND WEATHER EFFECTS:
Winter: Outside air is colder and denser.
  Temperature difference between flue gas and outside air is larger.
  Draft is naturally stronger in winter.
Draft may be 1 to 2 Pascals stronger in winter than in summer.
Strong wind: Can create downdraught (wind pushing air back down chimney)
  or can enhance draft (Venturi effect at chimney top).
  Effect depends on wind direction relative to chimney orientation.

TREND MONITORING:
If draft pressure becomes less negative by 0.5 Pa per month:
  Soot buildup is accumulating, narrowing the chimney.
  Schedule sweeping before draft falls below minus 2 Pa.
If draft pressure suddenly changes by more than 1 Pa:
  Physical obstruction or structural event.
  Inspect chimney before next operation.
        """
    },

]

# Validation layer

def validate_documents():
    """Check All documents have
    required fields and unique IDs
    """
    ids = []
    errors = []
    for i , doc in enumerate(KNOWLEDGE_DOCUMENTS):
        # Check required fields
        for field in ["id", "category", "title", "content"]:
            if field not in doc:
                errors.append(f"Document {i}: missing field ' {field}'")
        if "id" in doc:
            if doc["id"] in ids:
                errors.append(f"Duplicate ID: {doc['id']}")
            ids.append(doc["id"])
        if "content" in doc and len(doc["content"].strip()) < 100:
            errors.append(f"Document {i}: content too short")
    return errors

if __name__ == "__main__":
    errors = validate_documents()
    if errors:
        print("Validation errors found:")
        for error in errors:
            print(error)
    else:
        print(f"✅ All {len(KNOWLEDGE_DOCUMENTS)} documents valid")
        categories = {}
        for doc in KNOWLEDGE_DOCUMENTS:
            cat = doc.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        for cat, count in categories.items():
            print(f"   {cat}: {count} documents")