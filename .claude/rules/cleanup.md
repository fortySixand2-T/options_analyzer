# Cleanup Rules
# Reference when doing file cleanup or reorganization

## Files to DELETE (dead code, wrong timeframe, or superseded)
```
src/opportunity_builder.py
src/strategy_selector.py
src/formatter.py
src/ai_narrative.py
src/utils/config.py
src/utils/data_export.py
src/utils/__init__.py
EXTENSIONS.md
USECASES.md
activate_env.sh
build.sh
frontend/src/assets/hero.png
frontend/src/assets/react.svg
frontend/src/assets/vite.svg
```

## Files already moved to _deferred/ (DO NOT delete)
```
src/strategies/_deferred/calendar_spread.py
src/strategies/_deferred/diagonal_spread.py
src/strategies/_deferred/short_strangle.py
src/strategies/_deferred/long_straddle.py
src/strategies/_deferred/naked_put_1dte.py
```

## Files already moved to examples/ (useful reference, not scanner code)
```
examples/options_analyzer.py
examples/options_test_runner.py
examples/mc_runner.py
examples/scenario_runner.py
examples/vol_surface_runner.py
examples/simulations.py
examples/visualization.py
```

## Verify after any cleanup
Run `./start.sh test` to confirm nothing broke.
