# Strategy Rules
# Applies when working in: src/strategies/

## Active strategies (5 total, defined-risk only)
- iron_condor.py: dte_range=(7,14), iv_range=(40,100), requires LONG_GAMMA
- credit_spread.py: dte_range=(3,10), iv_range=(30,100), requires directional bias
- debit_spread.py: dte_range=(3,14), iv_range=(0,40), requires directional bias
- butterfly.py: dte_range=(0,7), center at max pain (not ATM)

## base.py evaluate() signature
Must accept dealer_regime parameter.
Score formula: weighted component formula from SIGNALS.md conviction weights.
NOT the old 60% checklist + 40% conviction formula.

## Deferred strategies (_deferred/)
Calendar, diagonal, strangle, straddle, naked_put_1dte.
These are for a future swing tab (14-60 DTE). Do NOT delete them.
They need different signals: SMA 50/200, IV term structure slope, earnings calendar.
Do NOT import or register deferred strategies in the active scanner.

## Exit rules
| Strategy | Profit target | Stop loss | Time exit |
|---|---|---|---|
| Iron condor | 50% credit | 2x credit | Close at 1 DTE |
| Credit spread | 50% credit | 2x credit | Close at 1 DTE |
| Debit spread | 50-75% debit | 50% debit | Close at 2 DTE |
| Butterfly | 100%+ debit | Full debit | Close at 0 DTE |
