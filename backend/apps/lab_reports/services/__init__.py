"""Lab report business logic. Views stay thin and call these modules:

    ocr        read text (and a confidence score) from an uploaded file
    extractor  turn the text into structured, untrusted data (missing → None)
    verifier   identity gate: does the report belong to this patient?
    validator  unit conversion, plausibility ranges, flags
    dashboard  preview, confirm (update rules), dashboard data and trends
"""
