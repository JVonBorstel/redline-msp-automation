"""Python lever modules. A registry `entry` of the form `levers.python.<module>:<function>` may resolve only here.

One module per lever family (B-14). A handler has the shape `handler(state, params) -> Any` and raises
`core.levers.handlers.LeverFailed` for an expected failure (STD-LV-8). It gets one client's state copy and
validated params, never an identity, a path, a credential or another client's data.
"""
