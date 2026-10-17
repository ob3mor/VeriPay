"""VeriPay API application package (Phase 1 foundation).

Modular monolith (docs/ARCHITECTURE.md §5): core/db have no internal deps,
feature modules depend downward, api/v1 only composes HTTP surfaces.
"""
