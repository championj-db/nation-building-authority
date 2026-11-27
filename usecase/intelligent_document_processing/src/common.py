"""Shared contract for the intelligent document processing use case.

Every pipeline step imports this module so that document types, extraction schemas, check codes,
payment-term rules and table names agree. Use cases never import each other (see
../../CONTRIBUTING.md); if a definition changes, it changes here.

No environment-specific value lives in this file: catalog, schema and volume arrive as job
parameters, never as literals.

Data provenance
  public     AusTender contract notices (api.tenders.gov.au, OCDS). Fetched at run time. Only the
             description, UNSPSC category, value, dates and procurement method are kept. Supplier
             names, supplier ids, contract notice ids and the procuring entity are discarded.
  synthetic  suppliers, purchase orders, goods receipts, every document in the inbox, processing
             history and ground truth. Seeded and deterministic. No record describes a real
             business or person.
"""

from __future__ import annotations

import datetime as dt
import json
import os

# ---------------------------------------------------------------------------
# The buying entity (fictional). Every invoice in the corpus should be addressed to it.
# ---------------------------------------------------------------------------
BUYER_NAME = "Nation Building Authority"
# Synthetic ABN generated to pass the ATO check-digit test. Any match with a real ABN is coincidental.
BUYER_ABN = "25 357 576 716"
BUYER_ADDRESS = ["Accounts Payable", "GPO Box 2026", "Canberra ACT 2601"]
BUYER_AP_EMAIL = "accounts.payable@nba.example.gov.au"

# ---------------------------------------------------------------------------
# Supplier Pay On-Time or Pay Interest Policy (RMG 417)
# https://www.finance.gov.au/publications/resource-management-guides/supplier-pay-time-or-pay-interest-policy-rmg-417
# Procurement Policy Note, updated payment terms from 1 January 2027:
# https://www.finance.gov.au/government/procurement/procurement-policy-notes/updated-commonwealth-supplier-payment-terms
#
# The clock starts the day after BOTH satisfactory delivery is acknowledged AND a correctly
# rendered invoice is received. The workbench applies the terms in force on that trigger date.
# ---------------------------------------------------------------------------
TERMS_CHANGE_DATE = dt.date(2027, 1, 1)
TERM_CALENDAR_DAYS = 20          # current maximum, invoices other than Peppol e-invoices
TERM_EINVOICE_CALENDAR_DAYS = 5  # current maximum, eligible Peppol e-invoices
TERM_BUSINESS_DAYS_2027 = 10     # all invoice types from 1 January 2027
INTEREST_PAYABLE_OVER_AUD = 100.0  # accrued interest is paid when it exceeds A$100
# ATO general interest charge, annual rate, October-December 2026 quarter:
# https://www.ato.gov.au/tax-rates-and-codes/general-interest-charge-rates
# A job parameter overrides it; the quarter label travels with every computed figure.
GIC_ANNUAL_RATE_DEFAULT = 0.1151
GIC_QUARTER_DEFAULT = "Oct-Dec 2026"

# ATO tax invoice requirements: recipient identity or ABN is required for taxable sales of
# A$1,000 or more. https://www.ato.gov.au/businesses-and-organisations/gst-excise-and-indirect-taxes/gst/tax-invoices
RECIPIENT_REQUIRED_FROM_AUD = 1000.0
GST_RATE = 0.10
GST_TOLERANCE_AUD = 0.05  # rounding allowance per invoice

# Business-day calendar: national public holidays plus the ACT, where the NBA is based.
CALENDAR_SUBDIVISION = "ACT"

# ---------------------------------------------------------------------------
# Confidence routing. ai_extract (v2.1) returns a per-field confidence_score and citations.
# The routing score combines it with grounding (the value is found in its cited text) and type
# validity. It decides who looks at a field. It is not a probability that the value is right.
# ---------------------------------------------------------------------------
REVIEW_THRESHOLD = 0.85     # any required field below this sends the document to a person
UNGROUNDED_PENALTY = 0.55   # multiplier when the value cannot be found anywhere in the document text
UNCITED_PENALTY = 0.88      # multiplier when it is in the document, but not in the region the model cited
INVALID_TYPE_PENALTY = 0.4  # multiplier when the value does not parse as its declared type

# ---------------------------------------------------------------------------
# Document types. Descriptions are passed to ai_classify; they matter more than the label.
# ---------------------------------------------------------------------------
DOC_TYPES = {
    "tax_invoice": {
        "label": "Tax invoice",
        "description": "A supplier's tax invoice or invoice requesting payment for goods or services, "
                       "with an invoice number, amounts and GST.",
    },
    "adjustment_note": {
        "label": "Adjustment note",
        "description": "An adjustment note or credit note that reduces or corrects an earlier invoice, "
                       "usually quoting the original invoice number.",
    },
    "supplier_statement": {
        "label": "Supplier statement",
        "description": "A statement of account listing several invoices, payments and an outstanding "
                       "balance. It does not itself request payment of a new supply.",
    },
    "correspondence": {
        "label": "Correspondence",
        "description": "A letter or email from a supplier: a payment query, a change of bank details, "
                       "a dispute about delivery, or other correspondence that is not an invoice.",
    },
    "quote": {
        "label": "Quote",
        "description": "A quotation, proposal or estimate for future work. It is not a request for "
                       "payment and does not belong in accounts payable.",
    },
}
INVOICE_TYPES = ("tax_invoice", "adjustment_note")

# ---------------------------------------------------------------------------
# Extraction schemas (ai_extract v2.1). Descriptions steer the model; types are enforced.
# REQUIRED_FIELDS gate routing: a required field below the threshold holds the document.
# ---------------------------------------------------------------------------
INVOICE_SCHEMA = {
    "document_title": {"type": "string", "description": "The title printed on the document, e.g. 'Tax invoice', 'Invoice', 'Adjustment note'."},
    "supplier_name": {"type": "string", "description": "Legal or trading name of the supplier issuing the document."},
    "supplier_abn": {"type": "string", "description": "The supplier's 11-digit Australian Business Number, digits only."},
    "recipient_name": {"type": "string", "description": "Name of the organisation the document is addressed to (bill to)."},
    "recipient_abn": {"type": "string", "description": "The recipient's ABN if shown, digits only."},
    "invoice_number": {"type": "string", "description": "The supplier's invoice or adjustment note number."},
    "original_invoice_number": {"type": "string", "description": "For an adjustment note, the invoice number it adjusts."},
    "invoice_date": {"type": "string", "description": "Date the document was issued, as YYYY-MM-DD."},
    "po_number": {"type": "string", "description": "Purchase order number quoted by the supplier, e.g. PO-4500123456."},
    "contract_reference": {"type": "string", "description": "Contract reference quoted by the supplier, e.g. NBA-C-10442."},
    "subtotal_ex_gst": {"type": "number", "description": "Total amount excluding GST, in AUD."},
    "gst_amount": {"type": "number", "description": "GST amount in AUD. Zero if no GST is charged."},
    "total_inc_gst": {"type": "number", "description": "Total amount payable including GST, in AUD. Negative or shown as a credit for an adjustment note."},
    "bank_bsb": {"type": "string", "description": "Bank BSB for payment, digits only."},
    "bank_account": {"type": "string", "description": "Bank account number for payment, digits only."},
}
INVOICE_REQUIRED_FIELDS = (
    "supplier_name", "supplier_abn", "recipient_name", "invoice_number", "invoice_date",
    "po_number", "subtotal_ex_gst", "gst_amount", "total_inc_gst",
)
# Field labels as the AP officer reads them, in display order.
INVOICE_FIELD_LABELS = {
    "supplier_name": "Supplier",
    "supplier_abn": "Supplier ABN",
    "recipient_name": "Addressed to",
    "recipient_abn": "Recipient ABN",
    "document_title": "Document title",
    "invoice_number": "Invoice number",
    "original_invoice_number": "Adjusts invoice",
    "invoice_date": "Invoice date",
    "po_number": "Purchase order",
    "contract_reference": "Contract reference",
    "subtotal_ex_gst": "Amount excl. GST",
    "gst_amount": "GST",
    "total_inc_gst": "Total incl. GST",
    "bank_bsb": "BSB",
    "bank_account": "Account number",
}
NUMBER_FIELDS = {"subtotal_ex_gst", "gst_amount", "total_inc_gst"}
DATE_FIELDS = {"invoice_date"}

STATEMENT_SCHEMA = {
    "supplier_name": {"type": "string", "description": "Name of the supplier issuing the statement."},
    "statement_date": {"type": "string", "description": "Statement date as YYYY-MM-DD."},
    "balance_due": {"type": "number", "description": "Total outstanding balance in AUD."},
    "overdue_amount": {"type": "number", "description": "Amount shown as overdue, in AUD. Zero if none."},
    "invoice_numbers": {"type": "array", "items": {"type": "string"}, "description": "Every invoice number listed on the statement."},
}

CORRESPONDENCE_SCHEMA = {
    "supplier_name": {"type": "string", "description": "Name of the supplier or sender."},
    "letter_date": {"type": "string", "description": "Date of the letter as YYYY-MM-DD."},
    "intent": {
        "type": "enum",
        "labels": ["payment_query", "bank_details_change", "delivery_dispute", "remittance_request", "other"],
        "description": "What the sender is asking for.",
    },
    "referenced_invoice_numbers": {"type": "array", "items": {"type": "string"}, "description": "Invoice numbers the letter refers to."},
    "new_bank_bsb": {"type": "string", "description": "If the letter gives new bank details, the BSB, digits only."},
    "new_bank_account": {"type": "string", "description": "If the letter gives new bank details, the account number, digits only."},
    "summary": {"type": "string", "description": "One sentence on what the sender wants, in plain English."},
}

CORRESPONDENCE_INTENTS = {
    "payment_query": {"label": "Payment query", "action": "Reply with the invoice status and pay-by date."},
    "bank_details_change": {"label": "Bank details change", "action": "Verify by calling the supplier on the number held in the vendor master, never the number in the letter. Do not update bank details from this document."},
    "delivery_dispute": {"label": "Delivery dispute", "action": "Refer to the contract manager. Delivery must be acknowledged before the payment clock starts."},
    "remittance_request": {"label": "Remittance request", "action": "Send remittance advice for paid invoices."},
    "other": {"label": "Other", "action": "Route to the AP team lead."},
}

# ---------------------------------------------------------------------------
# Correctly rendered checks. RMG 417 says an invoice must comply with the contract and be
# correctly calculated and due. The Commonwealth Contracting Suite model definition, and ATO
# tax-invoice rules, give the specific criteria below.
#   supplier_fault  True: failure means the invoice is not correctly rendered and goes back to
#                   the supplier, so the clock does not start. False: the fix is internal.
#   return_reason   the sentence sent to the supplier when the invoice is returned.
# ---------------------------------------------------------------------------
CCS_URL = "https://www.finance.gov.au/government/procurement/commonwealth-contracting-suite-ccs"
ATO_TAX_INVOICE_URL = "https://www.ato.gov.au/businesses-and-organisations/gst-excise-and-indirect-taxes/gst/tax-invoices"
RMG417_URL = "https://www.finance.gov.au/publications/resource-management-guides/supplier-pay-time-or-pay-interest-policy-rmg-417"

CHECKS = {
    "addressed_to_buyer": {
        "label": "Addressed to the Authority",
        "criterion": "The invoice is correctly addressed to the Nation Building Authority.",
        "source": "Commonwealth Contracting Suite", "url": CCS_URL,
        "supplier_fault": True,
        "return_reason": "The invoice is not addressed to the Nation Building Authority. Please reissue it to the correct entity.",
    },
    "tax_invoice_label": {
        "label": "Identified as a tax invoice",
        "criterion": "A GST-registered supplier's document is identifiable as a tax invoice.",
        "source": "ATO tax invoice requirements", "url": ATO_TAX_INVOICE_URL,
        "supplier_fault": True,
        "return_reason": "The document is not identified as a tax invoice. Please reissue it as a valid tax invoice.",
    },
    "supplier_abn_valid": {
        "label": "Supplier ABN is valid",
        "criterion": "The supplier ABN is shown and passes the ABN check-digit test.",
        "source": "ATO tax invoice requirements", "url": ATO_TAX_INVOICE_URL,
        "supplier_fault": True,
        "return_reason": "The ABN on the invoice is missing or not valid. Please reissue it with your correct ABN.",
    },
    "supplier_abn_matches_vendor": {
        "label": "ABN matches vendor record",
        "criterion": "The supplier ABN matches the ABN held in the vendor master for this purchase order.",
        "source": "Vendor master", "url": None,
        "supplier_fault": True,
        "return_reason": "The ABN on the invoice does not match the ABN we hold for your business. Please confirm and reissue.",
    },
    "recipient_identity": {
        "label": "Recipient identity shown",
        "criterion": "For a taxable sale of A$1,000 or more, the invoice shows the recipient's identity or ABN.",
        "source": "ATO tax invoice requirements", "url": ATO_TAX_INVOICE_URL,
        "supplier_fault": True,
        "return_reason": "For invoices of $1,000 or more the recipient's identity or ABN must be shown. Please reissue.",
    },
    "po_quoted": {
        "label": "Purchase order quoted",
        "criterion": "The invoice quotes the purchase order number the contract requires.",
        "source": "Commonwealth Contracting Suite", "url": CCS_URL,
        "supplier_fault": True,
        "return_reason": "The invoice does not quote a purchase order number. Please reissue it quoting the purchase order.",
    },
    "po_matches": {
        "label": "Purchase order matches",
        "criterion": "The quoted purchase order exists, is open, and was raised with this supplier.",
        "source": "Commonwealth Contracting Suite", "url": CCS_URL,
        "supplier_fault": True,
        "return_reason": "The purchase order quoted does not match an open order with your business. Please check the order number and reissue.",
    },
    "gst_calculated": {
        "label": "GST correctly calculated",
        "criterion": "GST is 10% of the taxable amount, and the total equals the amount plus GST.",
        "source": "ATO tax invoice requirements", "url": ATO_TAX_INVOICE_URL,
        "supplier_fault": True,
        "return_reason": "The GST or total on the invoice is not correctly calculated. Please correct the amounts and reissue.",
    },
    "within_po_value": {
        "label": "Within remaining order value",
        "criterion": "The amount does not exceed the value remaining on the purchase order and contract.",
        "source": "Commonwealth Contracting Suite", "url": CCS_URL,
        "supplier_fault": True,
        "return_reason": "The invoice exceeds the value remaining on the purchase order. Please contact your contract manager before reissuing.",
    },
    "not_duplicate": {
        "label": "Not already received",
        "criterion": "No other invoice from this supplier carries the same invoice number.",
        "source": "AP control", "url": None,
        "supplier_fault": True,
        "return_reason": "An invoice with this number has already been received. If this is a new invoice, please reissue it with a unique number.",
    },
    "delivery_acknowledged": {
        "label": "Delivery acknowledged",
        "criterion": "A goods or services receipt has been recorded against the purchase order.",
        "source": "RMG 417", "url": RMG417_URL,
        "supplier_fault": False,
        "return_reason": None,
    },
}
CHECK_ORDER = list(CHECKS)

# Document status. Exactly one per document, in this precedence order.
STATUSES = {
    "not_invoice": "Not an invoice",
    "exception": "Exception",
    "needs_review": "Needs review",
    "awaiting_delivery": "Awaiting delivery",
    "ready": "Ready to accept",
}

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
TABLES = {
    # public, pseudonymised
    "ref_contracts": "Contract notices from AusTender (public). Supplier identity and notice id replaced.",
    # synthetic master data
    "ref_suppliers": "Synthetic supplier vendor master.",
    "ref_purchase_orders": "Synthetic purchase orders against the contracts.",
    "ref_goods_receipts": "Synthetic goods and services receipts (delivery acknowledgement).",
    "ref_business_calendar": "Business-day calendar: weekends, national and ACT public holidays.",
    # synthetic corpus and ground truth
    "bronze_inbox_manifest": "Every document landed in the volume, with its arrival time and channel.",
    "bronze_ground_truth": "What each synthetic document really says, and the defects injected into it.",
    "bronze_processing_history": "Simulated AP decisions for documents received before the live queue window.",
    # pipeline outputs (Lakeflow) are bronze_parsed_documents, silver_classified_documents,
    # silver_invoice_extraction, silver_statement_extraction, silver_correspondence_extraction
}


def fq(catalog: str, schema: str, table: str) -> str:
    return f"`{catalog}`.`{schema}`.`{table}`"


def volume_dir(catalog: str, schema: str, volume: str, *parts: str) -> str:
    return "/".join([f"/Volumes/{catalog}/{schema}/{volume}", *parts])


def get_params(defaults: dict, dbutils) -> dict:
    """Read job parameters (widgets), creating them with defaults when run interactively."""
    out = {}
    for name, default in defaults.items():
        try:
            dbutils.widgets.text(name, str(default))
        except Exception:  # widget already exists
            pass
        value = dbutils.widgets.get(name)
        out[name] = value if value != "" else default
    return out


def add_src_to_path(dbutils) -> str:
    """Locate this folder from the src_dir parameter so notebooks can import the modules here."""
    import sys

    dbutils.widgets.text("src_dir", "")
    src = dbutils.widgets.get("src_dir").strip()
    found = next((c for c in [src, os.path.join(src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
    if found is None:
        raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
    if found not in sys.path:
        sys.path.insert(0, found)
    return found


def classify_labels_json() -> str:
    return json.dumps({k: v["description"] for k, v in DOC_TYPES.items()})


def schema_json(schema: dict) -> str:
    return json.dumps(schema)


def digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())
