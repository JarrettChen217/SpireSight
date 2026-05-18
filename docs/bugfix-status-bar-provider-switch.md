# Bug Fix: Status Bar Display Issue When Switching Providers

## Issue Description

When switching to an API provider that has no models available (e.g., `anthropic` in MVP), the status bar continued to display the previous model name (e.g., `gpt-5.5`), creating a mismatch between the displayed model and the actual active provider.

## Root Cause

1. `AnthropicProvider.list_models()` returns an empty list (not implemented in MVP)
2. `ProviderPicker._reload_models()` clears the model dropdown when switching to anthropic
3. `_model_box.currentData()` returns `None` when the dropdown is empty
4. `selection_changed` signal emits `("anthropic", "")` with an empty model_id
5. In `MainWindow._on_picker_changed()`, the condition `if model_id:` evaluates to `False`
6. **Status bar update is skipped**, leaving the old model name displayed

## Solution

Modified `MainWindow._on_picker_changed()` to handle the case when `model_id` is empty:

```python
def _on_picker_changed(self, provider: str, model_id: str) -> None:
    if provider:
        self._config.active_provider = provider
    if model_id:
        self._config.active_model = model_id
        self._usage_bar.set_model_label(model_id)
        self._compose.setEnabled(True)
        self._prompt_panel.setEnabled(True)
    else:
        # Provider has no models - show provider name and disable actions
        self._usage_bar.set_model_label(f"{provider} (no models)")
        self._compose.setEnabled(False)
        self._prompt_panel.setEnabled(False)
    self._store.save(self._config)
    self._refresh_inspect_availability()
```

## Changes Made

1. **Status bar update**: When `model_id` is empty, display `"{provider} (no models)"` instead of keeping the old model name
2. **UI state management**: Disable compose dock and prompt panel when no models are available, preventing users from attempting to use an unavailable provider
3. **User feedback**: Clear visual indication that the selected provider is not ready for use

## Testing

Added comprehensive test suite in `tests/test_status_bar_provider_switch.py`:

- ✅ Initial state shows correct model
- ✅ Switching to provider without models shows "(no models)" and disables UI
- ✅ Switching back to provider with models re-enables UI
- ✅ Multiple switches work correctly

All tests pass.

## Impact

- **User experience**: Users now see accurate status bar information at all times
- **Error prevention**: Disabled UI prevents attempts to use providers without models
- **Clarity**: "(no models)" message clearly indicates why the provider is unavailable

## Files Modified

- `src/spiresight/ui/windows/main_window.py` - Fixed `_on_picker_changed()` method
- `tests/test_status_bar_provider_switch.py` - Added test coverage

## Related

This fix is specific to the MVP implementation where some providers (anthropic, gemini) return empty model lists. When these providers are fully implemented, they will return models and the UI will work normally.
