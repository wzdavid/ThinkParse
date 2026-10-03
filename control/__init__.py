"""ThinkParse service layer.

Enterprise document parsing: durable jobs, capacity control, and public HTTP
APIs. This package does not load CUDA or engine weights; parsing runs in
external processes (MinerU 4.0, optional Docling). APIs: ``/api/v1`` and
``/api/v2``.
"""

__version__ = "2.0.0"
