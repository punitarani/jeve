"""Prose, rendered from typed state on demand (GEN-0001).

Nothing in `jeve.world`, `jeve.decide`, `jeve.memory` or `jeve.sim` may import
this package, and a test walks the import graph to keep it so. The simulation
produces typed facts; this turns some of them into sentences for a person to
read. The sentences are never read back.
"""
