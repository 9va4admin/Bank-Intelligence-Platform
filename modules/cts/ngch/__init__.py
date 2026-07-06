"""
modules/cts/ngch — CTS-2010 / Rev 3.0 NPCI spec implementation.

Components:
  pxf_iet_parser   — ItemExpiryTime parsing from PXF (P0 safety)
  pxf_parser       — Full PXF inward instrument parser
  iqa_engine       — 16-test IQA engine, UserField encoder
  signer           — MICRDS / ImageDS via HSM
  cxf_builder      — CXF XML builder (outward presentment)
  cibf_assembler   — CIBF binary assembler (front + back + ImageDS)
"""
