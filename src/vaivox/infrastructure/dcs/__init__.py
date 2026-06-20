"""DCS-side integration adapters (ADR-0012).

These adapters bridge VAIVOX to the live DCS radio-menu state that only exists inside the
mission's command-dialog panel:

- :mod:`~vaivox.infrastructure.dcs.menu_listener` receives the live F10 menu (label ->
  ``ActionIndex``) the VAIVOX DCS hook broadcasts, the authoritative source for F10 dispatch.
- :mod:`~vaivox.infrastructure.dcs.hook_installer` installs / self-heals that hook into the
  DCS radio-command panel so it survives DCS and VAICOM updates.
"""
